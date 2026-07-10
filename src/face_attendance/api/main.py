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
import threading
import time
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from face_attendance.api.auth import (
    CurrentUserDep,
    SettingsDep,
    StreamUserDep,
    authenticate_user,
    create_access_token,
    create_stream_ticket,
    require_jwt_secret,
    require_org_match,
    STREAM_TICKET_TTL,
)
from face_attendance.api.dependencies import get_settings, get_storage
from face_attendance.api.streaming import BOUNDARY, CameraStreamer
from face_attendance.contracts import AttendanceEvent, EmployeeRecord, UserRole
from face_attendance.storage import AttendanceStorage

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Provide the camera streamer without opening the camera at startup.

    The camera is a single shared device. Opening it eagerly here would reserve
    it (and burn recognition CPU) for the whole process lifetime even when
    nobody is watching the live feed - and block the CLI's enroll/attend from
    using it. So the streamer is created but not started: it opens lazily on the
    first ``/orgs/{org_id}/stream`` request and auto-stops after an idle window
    with no viewers (see ``CameraStreamer``). Shutdown still tears the camera
    down if a viewer left it running.
    """

    app.state.streamer = CameraStreamer(get_settings())
    try:
        yield
    finally:
        app.state.streamer.stop()


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

# How many failed logins from one client IP are tolerated before the expensive
# password check is short-circuited, and the window those failures are counted
# over.
_LOGIN_MAX_FAILURES = 5
_LOGIN_WINDOW_SECONDS = 60.0


class _LoginRateLimiter:
    """In-process, per-IP failed-login limiter guarding the expensive PBKDF2
    check on ``POST /auth/login`` against unauthenticated CPU exhaustion.

    Fixed-window count of *failed* attempts per client IP; a successful login
    clears that IP's counter. State lives in this process only, which is
    acceptable for the current single-instance deployment - a multi-instance
    deployment would need shared state (e.g. Redis), which is out of scope here.
    """

    def __init__(self, max_failures: int, window_seconds: float) -> None:
        self._max_failures = max_failures
        self._window = window_seconds
        self._failures: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def retry_after(self, client_ip: str) -> int | None:
        """Seconds the IP must wait if it is currently blocked, else ``None``."""

        now = time.monotonic()
        with self._lock:
            recent = self._recent_locked(client_ip, now)
            if len(recent) >= self._max_failures:
                return max(1, int(self._window - (now - recent[0])) + 1)
            return None

    def record_failure(self, client_ip: str) -> None:
        now = time.monotonic()
        with self._lock:
            recent = self._recent_locked(client_ip, now)
            recent.append(now)
            self._failures[client_ip] = recent

    def reset(self, client_ip: str) -> None:
        with self._lock:
            self._failures.pop(client_ip, None)

    def _recent_locked(self, client_ip: str, now: float) -> list[float]:
        """Drop timestamps older than the window; caller holds the lock."""

        recent = [t for t in self._failures.get(client_ip, []) if now - t < self._window]
        self._failures[client_ip] = recent
        return recent


_login_rate_limiter = _LoginRateLimiter(_LOGIN_MAX_FAILURES, _LOGIN_WINDOW_SECONDS)


class LoginRequest(BaseModel):
    # Field lengths are bounded so a caller cannot push a pathologically large
    # payload into the password hasher. 254 is the practical email-address cap.
    email: str = Field(max_length=254)
    password: str = Field(max_length=256)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class StreamTicketResponse(BaseModel):
    ticket: str
    expires_in: int


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness check with no database dependency."""

    return {"status": "ok"}


@app.post("/auth/login", response_model=TokenResponse)
def login(
    body: LoginRequest,
    request: Request,
    storage: StorageDep,
    settings: SettingsDep,
) -> TokenResponse:
    """Exchange email/password for a bearer token; 401 on any bad credential.

    Rate-limited per client IP: after too many failed attempts in a short
    window the expensive PBKDF2 check is skipped and 429 is returned, so an
    unauthenticated caller cannot exhaust CPU. Limiting is by IP, not by email,
    on purpose - keying on email would let an attacker lock out a real user.
    A successful login clears the caller's failure counter.
    """

    client_ip = request.client.host if request.client else "unknown"
    retry_after = _login_rate_limiter.retry_after(client_ip)
    if retry_after is not None:
        raise HTTPException(
            status_code=429,
            detail="too many failed login attempts; try again later",
            headers={"Retry-After": str(retry_after)},
        )

    user = authenticate_user(storage, body.email, body.password)
    if user is None:
        _login_rate_limiter.record_failure(client_ip)
        raise HTTPException(status_code=401, detail="invalid email or password")
    _login_rate_limiter.reset(client_ip)
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
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[AttendanceEvent]:
    """Attendance events for an org, optionally filtered by employee and capped
    to the newest ``limit`` (mirrors ``list_attendance_events``).

    ``limit`` is always a concrete, server-bounded value: it defaults to 100 and
    is hard-capped at 500 regardless of what the caller passes or omits, so a
    single request can never trigger an unbounded ``fetchall()`` as attendance
    history grows. This is a deliberate cap-only fix; true keyset/cursor
    pagination would be the next step if reports need to page through very large
    histories.

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
    org_id: str, request: Request, user: StreamUserDep, settings: SettingsDep
) -> StreamingResponse:
    """Live annotated MJPEG feed from this org's single camera.

    admin/manager only - ``employee`` gets 403 (consistent with employee being
    self-service-only elsewhere). Auth accepts a bearer header or a short-lived
    stream-only ``?ticket=`` query credential. Returns 503 rather than hanging
    when no camera is available.
    """

    require_org_match(user, org_id)
    if user.role == UserRole.EMPLOYEE:
        raise HTTPException(
            status_code=403, detail="employees may not view the live feed"
        )
    # One API process owns one physical camera and one recognition pipeline.
    # That pipeline is built for FA_ORG_ID, so no other tenant may receive its
    # frames even when that tenant has a valid admin/manager token.
    if org_id != settings.org_id:
        raise HTTPException(
            status_code=403,
            detail="live camera is not assigned to this organization",
        )
    streamer = request.app.state.streamer
    if streamer is None:
        raise HTTPException(
            status_code=503, detail="live camera stream is unavailable"
        )
    # Lazy cold start: the camera opens on this first request rather than at
    # process startup. On a Windows cold start this can block 60-90s before
    # frames flow (documented OS latency, not a bug); a camera/model failure
    # becomes a 503 rather than a 500 or a hang.
    try:
        streamer.ensure_started()
    except Exception as exc:  # noqa: BLE001 - any open failure is an unavailable feed
        logger.warning("live camera stream unavailable: %s", exc)
        raise HTTPException(
            status_code=503, detail="live camera stream is unavailable"
        ) from exc
    if not streamer.available:
        raise HTTPException(
            status_code=503, detail="live camera stream is unavailable"
        )
    return StreamingResponse(
        streamer.viewer_stream(),
        media_type=f"multipart/x-mixed-replace; boundary={BOUNDARY}",
        headers={
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.post("/orgs/{org_id}/stream-ticket", response_model=StreamTicketResponse)
def issue_stream_ticket(
    org_id: str,
    response: Response,
    user: CurrentUserDep,
    settings: SettingsDep,
) -> StreamTicketResponse:
    """Issue a one-minute, stream-only ticket to this camera's operators."""

    require_org_match(user, org_id)
    if user.role == UserRole.EMPLOYEE:
        raise HTTPException(
            status_code=403, detail="employees may not view the live feed"
        )
    if org_id != settings.org_id:
        raise HTTPException(
            status_code=403,
            detail="live camera is not assigned to this organization",
        )
    response.headers["Cache-Control"] = "no-store"
    ticket = create_stream_ticket(user, require_jwt_secret(settings))
    return StreamTicketResponse(
        ticket=ticket, expires_in=int(STREAM_TICKET_TTL.total_seconds())
    )
