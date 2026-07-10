"""Read-only HTTP API: employee/attendance reporting, 404s, limit, and the
tenant-isolation guarantee carried over from Phase 2 - an org_id in the URL
only ever sees that org's data."""

import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from face_attendance.api.dependencies import get_storage
from face_attendance.api.main import app
from face_attendance.contracts import (
    AttendanceEvent,
    AttendanceEventType,
    EmployeeRecord,
)
from face_attendance.storage import AttendanceStorage, initialize_database

NOW = datetime(2026, 7, 10, 9, 0, tzinfo=timezone.utc)


def _seed_employee(storage: AttendanceStorage, org_id: str, employee_id: str) -> None:
    storage.ensure_organization(org_id, org_id)
    storage.add_employee(
        EmployeeRecord(
            org_id=org_id,
            employee_id=employee_id,
            full_name=f"Name {employee_id}",
            created_at=NOW,
        )
    )


def _seed_event(
    storage: AttendanceStorage,
    org_id: str,
    employee_id: str,
    occurred_at: datetime,
    event_type: AttendanceEventType,
) -> None:
    storage.add_attendance_event(
        AttendanceEvent(
            org_id=org_id,
            employee_id=employee_id,
            occurred_at=occurred_at,
            event_type=event_type,
            confidence_score=0.9,
            match_distance=0.1,
        )
    )


class ApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        db_path = Path(self._temp.name) / "attendance.db"
        initialize_database(db_path)
        self.storage = AttendanceStorage(db_path)

        # Two orgs so isolation is exercised against a populated neighbour.
        _seed_employee(self.storage, "acme", "EMP-001")
        _seed_employee(self.storage, "acme", "EMP-002")
        _seed_employee(self.storage, "globex", "EMP-999")

        # A run of acme events (oldest -> newest) plus one globex event.
        for offset, kind in enumerate(
            [
                AttendanceEventType.CLOCK_IN,
                AttendanceEventType.CLOCK_OUT,
                AttendanceEventType.CLOCK_IN,
            ]
        ):
            _seed_event(
                self.storage,
                "acme",
                "EMP-001",
                NOW + timedelta(minutes=offset),
                kind,
            )
        _seed_event(self.storage, "globex", "EMP-999", NOW, AttendanceEventType.CLOCK_IN)

        app.dependency_overrides[get_storage] = lambda: self.storage
        self.addCleanup(app.dependency_overrides.clear)
        self.client = TestClient(app)

    def test_health_needs_no_database(self) -> None:
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_list_employees_returns_org_roster(self) -> None:
        response = self.client.get("/orgs/acme/employees")
        self.assertEqual(response.status_code, 200)
        ids = [row["employee_id"] for row in response.json()]
        self.assertEqual(ids, ["EMP-001", "EMP-002"])

    def test_unknown_org_returns_empty_list(self) -> None:
        response = self.client.get("/orgs/nope/employees")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_get_employee_found(self) -> None:
        response = self.client.get("/orgs/acme/employees/EMP-001")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["full_name"], "Name EMP-001")

    def test_get_unknown_employee_is_404(self) -> None:
        response = self.client.get("/orgs/acme/employees/EMP-404")
        self.assertEqual(response.status_code, 404)

    def test_attendance_list_and_limit(self) -> None:
        full = self.client.get("/orgs/acme/attendance")
        self.assertEqual(full.status_code, 200)
        self.assertEqual(len(full.json()), 3)

        limited = self.client.get("/orgs/acme/attendance", params={"limit": 2})
        self.assertEqual(limited.status_code, 200)
        events = limited.json()
        # Newest two, returned in chronological order (mirrors storage).
        self.assertEqual(len(events), 2)
        self.assertLess(events[0]["occurred_at"], events[1]["occurred_at"])

    def test_attendance_filter_by_employee(self) -> None:
        response = self.client.get(
            "/orgs/acme/attendance", params={"employee_id": "EMP-002"}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_attendance_limit_must_be_positive(self) -> None:
        response = self.client.get("/orgs/acme/attendance", params={"limit": 0})
        self.assertEqual(response.status_code, 422)

    def test_tenant_isolation_across_all_routes(self) -> None:
        # globex's employee and event never surface through an acme URL...
        acme_ids = [
            row["employee_id"]
            for row in self.client.get("/orgs/acme/employees").json()
        ]
        self.assertNotIn("EMP-999", acme_ids)
        self.assertEqual(
            self.client.get("/orgs/acme/employees/EMP-999").status_code, 404
        )

        # ...and every event under the acme URL belongs to acme only.
        acme_events = self.client.get("/orgs/acme/attendance").json()
        self.assertTrue(acme_events)
        self.assertTrue(all(e["org_id"] == "acme" for e in acme_events))

        # The globex URL sees only its own single event.
        globex_events = self.client.get("/orgs/globex/attendance").json()
        self.assertEqual(len(globex_events), 1)
        self.assertEqual(globex_events[0]["org_id"], "globex")


if __name__ == "__main__":
    unittest.main()
