"""Operator reports: attendance history and employee roster."""

from __future__ import annotations

from typing import Callable

from face_attendance.storage import AttendanceStorage


def print_attendance_report(
    storage: AttendanceStorage,
    org_id: str,
    employee_id: str | None = None,
    limit: int = 50,
    on_message: Callable[[str], None] = print,
) -> int:
    """Print recent attendance events for one org; returns the number printed."""

    events = storage.list_attendance_events(
        org_id, employee_id=employee_id, limit=limit
    )
    if not events:
        scope = f" for {employee_id}" if employee_id else ""
        on_message(f"no attendance events recorded{scope}")
        return 0

    on_message(f"{'when':<26} {'employee':<12} {'event':<10} {'confidence':<10} distance")
    for event in events:
        on_message(
            f"{event.occurred_at.isoformat(timespec='seconds'):<26} "
            f"{event.employee_id:<12} "
            f"{event.event_type.value:<10} "
            f"{event.confidence_score:<10.2f} "
            f"{event.match_distance:.3f}"
        )
    return len(events)


def print_employees(
    storage: AttendanceStorage,
    org_id: str,
    on_message: Callable[[str], None] = print,
) -> int:
    """Print one org's employee roster; returns the number of employees."""

    employees = storage.list_employees(org_id)
    if not employees:
        on_message("no employees enrolled")
        return 0

    on_message(f"{'employee':<12} {'active':<8} {'enrolled at':<26} name")
    for employee in employees:
        on_message(
            f"{employee.employee_id:<12} "
            f"{'yes' if employee.is_active else 'no':<8} "
            f"{employee.created_at.isoformat(timespec='seconds'):<26} "
            f"{employee.full_name}"
        )
    return len(employees)
