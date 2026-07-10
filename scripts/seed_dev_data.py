"""Seed a local dev database with a small org, roster, and attendance events.

The web frontend skeleton (``frontend/``) needs real rows to render, but the
normal enrollment path requires a camera. This stdlib-only script writes a
handful of employees and attendance events straight through ``AttendanceStorage``
so the API has something to serve during local development. It is a dev
convenience only - never part of the production data path.

Usage (writes to ``FA_DATABASE_PATH`` or the default ``data/attendance.db``):

    face-attendance init-db          # create the schema first
    python scripts/seed_dev_data.py  # then seed the "acme" org
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from face_attendance.api.auth import hash_password
from face_attendance.config import AppSettings
from face_attendance.contracts import (
    AttendanceEvent,
    AttendanceEventType,
    EmployeeRecord,
    UserRecord,
    UserRole,
)
from face_attendance.storage import AttendanceStorage

ORG_ID = "acme"

EMPLOYEES = [
    ("EMP-001", "Ada Lovelace"),
    ("EMP-002", "Alan Turing"),
    ("EMP-003", "Grace Hopper"),
]

# LOCAL DEV FIXTURE ONLY - obviously-fake .test accounts with a shared,
# clearly-labeled throwaway password, so a developer can log in and try each
# role against the local API. These are NEVER for production: real users are
# provisioned with unique, secret passwords through a real path.
DEV_PASSWORD = "devpassword123"  # noqa: S105 - intentional dev fixture credential
DEV_USERS = [
    ("admin@acme.test", UserRole.ADMIN, None),
    ("manager@acme.test", UserRole.MANAGER, None),
    ("employee@acme.test", UserRole.EMPLOYEE, "EMP-001"),
]


def main() -> None:
    settings = AppSettings.from_env()
    storage = AttendanceStorage(settings.database_path)
    storage.ensure_organization(ORG_ID, "Acme Corp")

    now = datetime.now(timezone.utc)
    for index, (employee_id, full_name) in enumerate(EMPLOYEES):
        storage.add_employee(
            EmployeeRecord(
                org_id=ORG_ID,
                employee_id=employee_id,
                full_name=full_name,
                is_active=True,
                created_at=now - timedelta(days=30),
            )
        )
        # One clock-in and one clock-out per employee so the events table renders.
        storage.add_attendance_event(
            AttendanceEvent(
                org_id=ORG_ID,
                employee_id=employee_id,
                occurred_at=now - timedelta(hours=9, minutes=index),
                event_type=AttendanceEventType.CLOCK_IN,
                confidence_score=0.98,
                match_distance=0.21,
            )
        )
        storage.add_attendance_event(
            AttendanceEvent(
                org_id=ORG_ID,
                employee_id=employee_id,
                occurred_at=now - timedelta(minutes=index),
                event_type=AttendanceEventType.CLOCK_OUT,
                confidence_score=0.97,
                match_distance=0.24,
            )
        )

    password_hash = hash_password(DEV_PASSWORD)
    for user_id, role, employee_id in DEV_USERS:
        storage.add_user(
            UserRecord(
                org_id=ORG_ID,
                user_id=user_id,
                role=role,
                password_hash=password_hash,
                employee_id=employee_id,
                created_at=now,
            )
        )

    print(f"Seeded org '{ORG_ID}' with {len(EMPLOYEES)} employees into {settings.database_path}")
    print(f"Seeded {len(DEV_USERS)} dev login users (LOCAL DEV ONLY, password '{DEV_PASSWORD}'):")
    for user_id, role, employee_id in DEV_USERS:
        link = f" -> {employee_id}" if employee_id else ""
        print(f"  {role.value:8} {user_id}{link}")


if __name__ == "__main__":
    main()
