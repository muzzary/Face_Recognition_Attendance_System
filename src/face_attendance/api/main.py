"""Read-only HTTP API over the tenant-scoped attendance storage layer.

Every data route is scoped by an ``org_id`` path segment and delegates
straight to ``AttendanceStorage``, whose reads already filter by org - so a
tenant can only ever see its own rows (the Phase 2 isolation guarantee carried
through to HTTP). Reads are guarded by JWT auth (Phase 5): every data route
requires a valid token whose ``org_id`` matches the URL, and ``employee``-role
tokens are further restricted to their own record. There are still no write
endpoints.

An unknown org is not distinguishable from an org with no rows at the storage
layer (reads filter by org id and simply return nothing), so the collection
routes return an empty list rather than 404 for an unknown org. A missing
single employee returns 404.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from face_attendance.api.auth import (
    CurrentUserDep,
    SettingsDep,
    StreamUserDep,
    authenticate_user,
    create_access_token,
    require_jwt_secret,
    require_org_match,
)
from face_attendance.api.dependencies import get_settings, get_storage
from face_attendance.api.streaming import BOUNDARY, CameraStreamer, mjpeg_stream
from face_attendance.contracts import AttendanceEvent, EmployeeRecord, UserRole
from face_attendance.storage import AttendanceStorage

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Own the camera for the API's lifetime: start the recognition/stream loop
    on startup, stop it on shutdown.

    The camera is a single shared device, so the API process (not a script per
    run) now owns it. If it cannot open - no camera on a dev/CI box, or missing
    models - the streaming feature is disabled with a warning while the rest of
    the API keeps serving; ``/orgs/{org_id}/stream`` then returns 503.
    """

    streamer = CameraStreamer(get_settings())
    try:
        streamer.start()
        logger.info("live camera stream started")
    except Exception as exc:  # noqa: BLE001 - the API must start without a camera
        logger.warning("live camera stream unavailable: %s", exc)
    app.state.streamer = streamer
    try:
        yield
    finally:
        streamer.stop()


app = FastAPI(
    title="Face Attendance API",
    version="1.0.0",
    summary="Read-only reporting over tenant-scoped attendance data.",
    lifespan=lifespan,
)

# Set before any lifespan runs so routes can check it even in tests (which do
# not trigger startup): no streamer means the stream feature is unavailable.
app.state.streamer = None

# Dev-only CORS: the browser frontend (Vite dev server) runs on a different
# origin than the API, so the browser blocks fetches without these headers.
# This is a permissive local-development allow-list; a real cross-origin policy
# arrives with auth in a later phase.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

StorageDep = Annotated[AttendanceStorage, Depends(get_storage)]


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness check with no database dependency."""

    return {"status": "ok"}


@app.post("/auth/login", response_model=TokenResponse)
def login(
    body: LoginRequest, storage: StorageDep, settings: SettingsDep
) -> TokenResponse:
    """Exchange email/password for a bearer token; 401 on any bad credential."""

    user = authenticate_user(storage, body.email, body.password)
    if user is None:
        raise HTTPException(status_code=401, detail="invalid email or password")
    token = create_access_token(user, require_jwt_secret(settings))
    return TokenResponse(access_token=token)


@app.get("/orgs/{org_id}/employees", response_model=list[EmployeeRecord])
def list_employees(
    org_id: str, storage: StorageDep, user: CurrentUserDep
) -> list[EmployeeRecord]:
    """Full org roster. admin/manager only - employees are denied the roster."""

    require_org_match(user, org_id)
    if user.role == UserRole.EMPLOYEE:
        raise HTTPException(
            status_code=403, detail="employees may not read the full roster"
        )
    return storage.list_employees(org_id)


@app.get("/orgs/{org_id}/employees/{employee_id}", response_model=EmployeeRecord)
def get_employee(
    org_id: str, employee_id: str, storage: StorageDep, user: CurrentUserDep
) -> EmployeeRecord:
    """Single employee, or 404. An employee may only read their own record."""

    require_org_match(user, org_id)
    if user.role == UserRole.EMPLOYEE and employee_id != user.employee_id:
        raise HTTPException(
            status_code=403, detail="employees may only read their own record"
        )
    employee = storage.get_employee(org_id, employee_id)
    if employee is None:
        raise HTTPException(
            status_code=404,
            detail=f"employee {employee_id} not found in org {org_id}",
        )
    return employee


@app.get("/orgs/{org_id}/attendance", response_model=list[AttendanceEvent])
def list_attendance(
    org_id: str,
    storage: StorageDep,
    user: CurrentUserDep,
    employee_id: Annotated[str | None, Query()] = None,
    limit: Annotated[int | None, Query(ge=1)] = None,
) -> list[AttendanceEvent]:
    """Attendance events for an org, optionally filtered by employee and capped
    to the newest ``limit`` (mirrors ``list_attendance_events``).

    An employee is silently scoped to their own events: they cannot request a
    different employee's events (403) nor pull the whole org by omitting the
    filter (the filter is forced to their own id).
    """

    require_org_match(user, org_id)
    if user.role == UserRole.EMPLOYEE:
        if employee_id is not None and employee_id != user.employee_id:
            raise HTTPException(
                status_code=403,
                detail="employees may only read their own attendance",
            )
        employee_id = user.employee_id
    return storage.list_attendance_events(org_id, employee_id=employee_id, limit=limit)


@app.get("/orgs/{org_id}/stream")
def stream_camera(
    org_id: str, request: Request, user: StreamUserDep
) -> StreamingResponse:
    """Live annotated MJPEG feed from this org's single camera.

    admin/manager only - ``employee`` gets 403 (consistent with employee being
    self-service-only elsewhere). Auth accepts the bearer token via the
    ``Authorization`` header or a ``?token=`` query param (see ``get_stream_user``
    - a browser cannot set headers on an ``<img>`` src). Returns 503 rather than
    hanging when no camera is available.
    """

    require_org_match(user, org_id)
    if user.role == UserRole.EMPLOYEE:
        raise HTTPException(
            status_code=403, detail="employees may not view the live feed"
        )
    streamer = request.app.state.streamer
    if streamer is None or not streamer.available:
        raise HTTPException(
            status_code=503, detail="live camera stream is unavailable"
        )
    return StreamingResponse(
        mjpeg_stream(streamer.jpeg_frame, streamer.stop_event),
        media_type=f"multipart/x-mixed-replace; boundary={BOUNDARY}",
    )
