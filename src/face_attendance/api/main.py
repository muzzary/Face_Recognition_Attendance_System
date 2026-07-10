"""Read-only HTTP API over the tenant-scoped attendance storage layer.

Every data route is scoped by an ``org_id`` path segment and delegates
straight to ``AttendanceStorage``, whose reads already filter by org - so a
tenant can only ever see its own rows (the Phase 2 isolation guarantee carried
through to HTTP). This phase is reporting only: no auth (Phase 5) and no write
endpoints.

An unknown org is not distinguishable from an org with no rows at the storage
layer (reads filter by org id and simply return nothing), so the collection
routes return an empty list rather than 404 for an unknown org. A missing
single employee returns 404.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query

from face_attendance.api.dependencies import get_storage
from face_attendance.contracts import AttendanceEvent, EmployeeRecord
from face_attendance.storage import AttendanceStorage

app = FastAPI(
    title="Face Attendance API",
    version="1.0.0",
    summary="Read-only reporting over tenant-scoped attendance data.",
)

StorageDep = Annotated[AttendanceStorage, Depends(get_storage)]


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness check with no database dependency."""

    return {"status": "ok"}


@app.get("/orgs/{org_id}/employees", response_model=list[EmployeeRecord])
def list_employees(org_id: str, storage: StorageDep) -> list[EmployeeRecord]:
    """All employees for an org (empty list if the org has none/does not exist)."""

    return storage.list_employees(org_id)


@app.get("/orgs/{org_id}/employees/{employee_id}", response_model=EmployeeRecord)
def get_employee(org_id: str, employee_id: str, storage: StorageDep) -> EmployeeRecord:
    """Single employee, or 404 if no such employee exists in this org."""

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
    employee_id: Annotated[str | None, Query()] = None,
    limit: Annotated[int | None, Query(ge=1)] = None,
) -> list[AttendanceEvent]:
    """Attendance events for an org, optionally filtered by employee and capped
    to the newest ``limit`` (mirrors ``list_attendance_events``)."""

    return storage.list_attendance_events(org_id, employee_id=employee_id, limit=limit)
