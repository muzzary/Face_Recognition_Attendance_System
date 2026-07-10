"""Auth + RBAC over the HTTP API: login, token verification, cross-org
isolation, and the per-role read scopes (admin/manager full, employee self-only)."""

import sqlite3
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

import jwt
from fastapi.testclient import TestClient

from face_attendance.api.auth import get_settings, hash_password
from face_attendance.api.dependencies import get_storage
from face_attendance.api.main import app
from face_attendance.config import AppSettings
from face_attendance.contracts import (
    AttendanceEvent,
    AttendanceEventType,
    EmployeeRecord,
    UserRecord,
    UserRole,
)
from face_attendance.storage import AttendanceStorage, initialize_database

NOW = datetime(2026, 7, 10, 9, 0, tzinfo=timezone.utc)
SECRET = "test-jwt-secret-0123456789abcdef0123"
PASSWORD = "correct horse"


class AuthTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        db_path = Path(self._temp.name) / "attendance.db"
        initialize_database(db_path)
        self.db_path = db_path
        self.storage = AttendanceStorage(db_path)

        for org in ("acme",):
            self.storage.ensure_organization(org, org)
        for employee_id in ("EMP-001", "EMP-002"):
            self.storage.add_employee(
                EmployeeRecord(
                    org_id="acme",
                    employee_id=employee_id,
                    full_name=f"Name {employee_id}",
                    created_at=NOW,
                )
            )
        # EMP-001 has two events, EMP-002 one, so self-scoping is observable.
        self._seed_event("EMP-001", AttendanceEventType.CLOCK_IN)
        self._seed_event("EMP-001", AttendanceEventType.CLOCK_OUT)
        self._seed_event("EMP-002", AttendanceEventType.CLOCK_IN)

        password_hash = hash_password(PASSWORD)
        self.storage.add_user(
            UserRecord(
                org_id="acme",
                user_id="admin@acme.test",
                role=UserRole.ADMIN,
                password_hash=password_hash,
                created_at=NOW,
            )
        )
        self.storage.add_user(
            UserRecord(
                org_id="acme",
                user_id="manager@acme.test",
                role=UserRole.MANAGER,
                password_hash=password_hash,
                created_at=NOW,
            )
        )
        self.storage.add_user(
            UserRecord(
                org_id="acme",
                user_id="employee@acme.test",
                role=UserRole.EMPLOYEE,
                password_hash=password_hash,
                employee_id="EMP-001",
                created_at=NOW,
            )
        )

        settings = AppSettings.from_env(environ={"FA_JWT_SECRET": SECRET})
        app.dependency_overrides[get_storage] = lambda: self.storage
        app.dependency_overrides[get_settings] = lambda: settings
        self.addCleanup(app.dependency_overrides.clear)
        self.client = TestClient(app)

    def _seed_event(self, employee_id: str, kind: AttendanceEventType) -> None:
        self.storage.add_attendance_event(
            AttendanceEvent(
                org_id="acme",
                employee_id=employee_id,
                occurred_at=NOW,
                event_type=kind,
                confidence_score=0.9,
                match_distance=0.1,
            )
        )

    def _login(self, email: str, password: str = PASSWORD):
        return self.client.post(
            "/auth/login", json={"email": email, "password": password}
        )

    def _token(self, email: str) -> str:
        return self._login(email).json()["access_token"]

    def _auth(self, email: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token(email)}"}

    # --- login ---------------------------------------------------------------

    def test_login_success_returns_bearer_token(self) -> None:
        response = self._login("admin@acme.test")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["token_type"], "bearer")
        self.assertTrue(body["access_token"])

    def test_login_wrong_password_is_401_and_generic(self) -> None:
        response = self._login("admin@acme.test", "nope")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()["detail"], "invalid email or password")

    def test_login_unknown_email_is_401_and_indistinguishable(self) -> None:
        response = self._login("ghost@acme.test")
        self.assertEqual(response.status_code, 401)
        # Same message as a wrong password: no email-existence leak.
        self.assertEqual(response.json()["detail"], "invalid email or password")

    # --- token verification --------------------------------------------------

    def test_missing_token_is_401(self) -> None:
        response = self.client.get("/orgs/acme/employees")
        self.assertEqual(response.status_code, 401)

    def test_invalid_token_is_401(self) -> None:
        response = self.client.get(
            "/orgs/acme/employees", headers={"Authorization": "Bearer garbage"}
        )
        self.assertEqual(response.status_code, 401)

    def test_expired_token_is_401(self) -> None:
        expired = jwt.encode(
            {
                "sub": "admin@acme.test",
                "org_id": "acme",
                "role": "admin",
                "employee_id": None,
                "exp": datetime.now(timezone.utc) - timedelta(hours=1),
            },
            SECRET,
            algorithm="HS256",
        )
        response = self.client.get(
            "/orgs/acme/employees", headers={"Authorization": f"Bearer {expired}"}
        )
        self.assertEqual(response.status_code, 401)

    def test_cross_org_token_is_403(self) -> None:
        response = self.client.get(
            "/orgs/other/employees", headers=self._auth("admin@acme.test")
        )
        self.assertEqual(response.status_code, 403)

    # --- role scopes ---------------------------------------------------------

    def test_admin_and_manager_get_full_roster(self) -> None:
        for email in ("admin@acme.test", "manager@acme.test"):
            response = self.client.get(
                "/orgs/acme/employees", headers=self._auth(email)
            )
            self.assertEqual(response.status_code, 200, email)
            self.assertEqual(len(response.json()), 2, email)

    def test_employee_denied_full_roster(self) -> None:
        response = self.client.get(
            "/orgs/acme/employees", headers=self._auth("employee@acme.test")
        )
        self.assertEqual(response.status_code, 403)

    def test_employee_allowed_own_record(self) -> None:
        response = self.client.get(
            "/orgs/acme/employees/EMP-001", headers=self._auth("employee@acme.test")
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["employee_id"], "EMP-001")

    def test_employee_denied_other_record(self) -> None:
        response = self.client.get(
            "/orgs/acme/employees/EMP-002", headers=self._auth("employee@acme.test")
        )
        self.assertEqual(response.status_code, 403)

    def test_employee_attendance_auto_scoped_to_self(self) -> None:
        headers = self._auth("employee@acme.test")
        # No filter given -> silently scoped to their own two events.
        own = self.client.get("/orgs/acme/attendance", headers=headers)
        self.assertEqual(own.status_code, 200)
        self.assertEqual(len(own.json()), 2)
        self.assertTrue(all(e["employee_id"] == "EMP-001" for e in own.json()))
        # Asking for someone else's events -> 403.
        other = self.client.get(
            "/orgs/acme/attendance",
            params={"employee_id": "EMP-002"},
            headers=headers,
        )
        self.assertEqual(other.status_code, 403)

    # --- revocation ------------------------------------------------------------
    # A JWT's claims are a snapshot at login time; get_current_user re-checks the
    # live user row on every request (_require_current_user in api/auth.py) so a
    # still-unexpired token stops working the moment the underlying account
    # changes, instead of granting stale access for the rest of its 8h lifetime.

    def _mutate_user_row(self, user_id: str, **columns: object) -> None:
        assignments = ", ".join(f"{column} = ?" for column in columns)
        connection = sqlite3.connect(self.db_path)
        try:
            connection.execute(
                f"UPDATE users SET {assignments} WHERE user_id = ?",
                (*columns.values(), user_id),
            )
            connection.commit()
        finally:
            connection.close()

    def test_deleted_user_token_is_rejected(self) -> None:
        headers = self._auth("employee@acme.test")
        connection = sqlite3.connect(self.db_path)
        try:
            connection.execute(
                "DELETE FROM users WHERE user_id = ?", ("employee@acme.test",)
            )
            connection.commit()
        finally:
            connection.close()

        response = self.client.get("/orgs/acme/employees/EMP-001", headers=headers)

        self.assertEqual(response.status_code, 401)

    def test_role_downgrade_invalidates_the_old_token(self) -> None:
        headers = self._auth("admin@acme.test")
        self._mutate_user_row("admin@acme.test", role="employee", employee_id="EMP-001")

        # The token still claims role=admin, but the live row now says
        # employee - the identity check must catch the mismatch and reject it
        # rather than honor the stale, now-too-privileged claim.
        response = self.client.get("/orgs/acme/employees", headers=headers)

        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
