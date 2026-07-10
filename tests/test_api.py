"""Read-only HTTP API: employee/attendance reporting, 404s, limit, and the
tenant-isolation guarantee carried over from Phase 2 - an org_id in the URL
only ever sees that org's data. All data routes are now behind an admin token
(Phase 5 auth); the per-role scopes are exercised in test_auth."""

import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

import jwt
from fastapi.testclient import TestClient

from face_attendance.api.auth import (
    AuthenticatedUser,
    create_access_token,
    create_stream_ticket,
    get_settings,
    hash_password,
)
from face_attendance.api.dependencies import get_storage
from face_attendance.api.main import app, _login_rate_limiter
from face_attendance.api.streaming import LatestJpegFrame
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

        # An admin per org so the read routes (now token-gated) are reachable.
        for org in ("acme", "globex"):
            self.storage.add_user(
                UserRecord(
                    org_id=org,
                    user_id=f"admin@{org}.test",
                    role=UserRole.ADMIN,
                    password_hash=hash_password("pw"),
                    created_at=NOW,
                )
            )

        settings = AppSettings.from_env(environ={"FA_JWT_SECRET": SECRET})
        app.dependency_overrides[get_storage] = lambda: self.storage
        app.dependency_overrides[get_settings] = lambda: settings
        self.addCleanup(app.dependency_overrides.clear)
        self.client = TestClient(app)
        # Default to the acme admin; globex assertions pass their own header.
        self.client.headers["Authorization"] = f"Bearer {self._token('acme')}"

    def _token(self, org: str) -> str:
        response = self.client.post(
            "/auth/login", json={"email": f"admin@{org}.test", "password": "pw"}
        )
        return response.json()["access_token"]

    def test_health_needs_no_database(self) -> None:
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_list_employees_returns_org_roster(self) -> None:
        response = self.client.get("/orgs/acme/employees")
        self.assertEqual(response.status_code, 200)
        ids = [row["employee_id"] for row in response.json()]
        self.assertEqual(ids, ["EMP-001", "EMP-002"])

    def test_other_org_is_forbidden(self) -> None:
        # Auth precedes the storage lookup: a token for one org is refused at
        # any other org's URL (403) before the empty-list logic is reached.
        response = self.client.get("/orgs/nope/employees")
        self.assertEqual(response.status_code, 403)

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

    def test_attendance_limit_is_capped(self) -> None:
        # The server hard-caps limit at 500 so no caller can request an
        # unbounded response, however large the history grows.
        response = self.client.get("/orgs/acme/attendance", params={"limit": 501})
        self.assertEqual(response.status_code, 422)

    def test_login_is_rate_limited_after_repeated_failures(self) -> None:
        # The limiter counts failed attempts for the TestClient's client IP;
        # reset it afterwards so it does not leak into other tests' logins.
        self.addCleanup(lambda: _login_rate_limiter.reset("testclient"))
        bad = {"email": "admin@acme.test", "password": "wrong"}
        for _ in range(5):  # the configured failure threshold
            self.assertEqual(
                self.client.post("/auth/login", json=bad).status_code, 401
            )
        blocked = self.client.post("/auth/login", json=bad)
        self.assertEqual(blocked.status_code, 429)
        self.assertIn("Retry-After", blocked.headers)

    def test_login_rejects_oversized_fields(self) -> None:
        response = self.client.post(
            "/auth/login",
            json={"email": "a" * 300, "password": "b" * 300},
        )
        self.assertEqual(response.status_code, 422)

    def test_tenant_isolation_across_all_routes(self) -> None:
        # globex's employee never surfaces through an acme URL (acme token)...
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

        # The acme token is refused at globex's URL (cross-org -> 403).
        self.assertEqual(
            self.client.get("/orgs/globex/attendance").status_code, 403
        )

        # A globex token sees only its own single event.
        globex_header = {"Authorization": f"Bearer {self._token('globex')}"}
        globex_events = self.client.get(
            "/orgs/globex/attendance", headers=globex_header
        ).json()
        self.assertEqual(len(globex_events), 1)
        self.assertEqual(globex_events[0]["org_id"], "globex")


class _FakeStreamer:
    """Stands in for a running CameraStreamer without any hardware."""

    def __init__(self, available: bool) -> None:
        self.jpeg_frame = LatestJpegFrame()
        self.stop_event = threading.Event()
        self.available = available


class StreamRouteTests(unittest.TestCase):
    """Auth/RBAC/availability for GET /orgs/{org_id}/stream (no camera needed)."""

    def setUp(self) -> None:
        self._temp = TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        db_path = Path(self._temp.name) / "attendance.db"
        initialize_database(db_path)
        self.storage = AttendanceStorage(db_path)
        self.storage.ensure_organization("acme", "Acme")
        self.storage.ensure_organization("globex", "Globex")
        self.storage.add_employee(
            EmployeeRecord(
                org_id="acme",
                employee_id="EMP-001",
                full_name="Employee",
                created_at=NOW,
            )
        )
        for role, org, employee_id in (
            (UserRole.ADMIN, "acme", None),
            (UserRole.MANAGER, "acme", None),
            (UserRole.EMPLOYEE, "acme", "EMP-001"),
            (UserRole.ADMIN, "globex", None),
            (UserRole.MANAGER, "globex", None),
        ):
            self.storage.add_user(
                UserRecord(
                    org_id=org,
                    user_id=f"{role.value}@{org}.test",
                    role=role,
                    password_hash="x",
                    employee_id=employee_id,
                    created_at=NOW,
                )
            )
        settings = AppSettings.from_env(
            environ={"FA_JWT_SECRET": SECRET, "FA_ORG_ID": "acme"}
        )
        app.dependency_overrides[get_storage] = lambda: self.storage
        app.dependency_overrides[get_settings] = lambda: settings
        self.addCleanup(app.dependency_overrides.clear)
        self.client = TestClient(app)
        # No streamer by default (lifespan is not run under a plain TestClient).
        app.state.streamer = None
        self.addCleanup(lambda: setattr(app.state, "streamer", None))

    def _token(self, role: UserRole, org: str = "acme", employee_id=None) -> str:
        user = UserRecord(
            org_id=org,
            user_id=f"{role.value}@{org}.test",
            role=role,
            password_hash="x",
            employee_id=employee_id,
            created_at=NOW,
        )
        return create_access_token(user, SECRET)

    def _ticket(self, role: UserRole, org: str = "acme", employee_id=None) -> str:
        return create_stream_ticket(
            AuthenticatedUser(
                user_id=f"{role.value}@{org}.test",
                org_id=org,
                role=role,
                employee_id=employee_id,
            ),
            SECRET,
        )

    def test_no_token_is_401(self) -> None:
        self.assertEqual(self.client.get("/orgs/acme/stream").status_code, 401)

    def test_invalid_token_is_401(self) -> None:
        response = self.client.get("/orgs/acme/stream?ticket=not-a-jwt")
        self.assertEqual(response.status_code, 401)

    def test_access_token_in_query_is_no_longer_accepted(self) -> None:
        token = self._token(UserRole.ADMIN)

        response = self.client.get(f"/orgs/acme/stream?token={token}")

        self.assertEqual(response.status_code, 401)

    def test_org_mismatch_is_403(self) -> None:
        app.state.streamer = _FakeStreamer(available=True)
        header = {"Authorization": f"Bearer {self._token(UserRole.ADMIN)}"}
        response = self.client.get("/orgs/globex/stream", headers=header)
        self.assertEqual(response.status_code, 403)

    def test_other_tenant_cannot_view_the_process_camera(self) -> None:
        app.state.streamer = _FakeStreamer(available=True)
        ticket = self._ticket(UserRole.ADMIN, org="globex")

        response = self.client.get(f"/orgs/globex/stream?ticket={ticket}")

        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            response.json()["detail"],
            "live camera is not assigned to this organization",
        )

    def test_unassigned_tenant_cannot_probe_camera_availability(self) -> None:
        ticket = self._ticket(UserRole.MANAGER, org="globex")

        response = self.client.get(f"/orgs/globex/stream?ticket={ticket}")

        self.assertEqual(response.status_code, 403)

    def test_employee_is_forbidden(self) -> None:
        app.state.streamer = _FakeStreamer(available=True)
        ticket = self._ticket(UserRole.EMPLOYEE, employee_id="EMP-001")
        response = self.client.get(f"/orgs/acme/stream?ticket={ticket}")
        self.assertEqual(response.status_code, 403)

    def test_camera_unavailable_is_503(self) -> None:
        # Both "no streamer at all" and "streamer present but not running" must
        # 503 rather than hang.
        ticket = self._ticket(UserRole.ADMIN)
        self.assertEqual(
            self.client.get(f"/orgs/acme/stream?ticket={ticket}").status_code, 503
        )
        app.state.streamer = _FakeStreamer(available=False)
        self.assertEqual(
            self.client.get(f"/orgs/acme/stream?ticket={ticket}").status_code, 503
        )

    def test_manager_streams_multipart_when_available(self) -> None:
        fake = _FakeStreamer(available=True)
        fake.jpeg_frame.put(b"\xff\xd8live\xff\xd9")
        app.state.streamer = fake
        ticket = self._ticket(UserRole.MANAGER)

        # The MJPEG generator is endless by design, so bound it for the test:
        # a timer flips the stop event, the generator ends, and a plain GET can
        # read the whole (now finite) body without hanging on the live stream.
        timer = threading.Timer(0.2, fake.stop_event.set)
        timer.start()
        self.addCleanup(timer.cancel)

        response = self.client.get(f"/orgs/acme/stream?ticket={ticket}")

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "multipart/x-mixed-replace", response.headers["content-type"]
        )
        # The pre-published frame came through the route with MJPEG framing.
        self.assertIn(b"--faframe", response.content)
        self.assertIn(b"\xff\xd8live\xff\xd9", response.content)

    def test_access_token_issues_short_lived_stream_ticket(self) -> None:
        headers = {"Authorization": f"Bearer {self._token(UserRole.ADMIN)}"}

        response = self.client.post("/orgs/acme/stream-ticket", headers=headers)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["expires_in"], 60)
        self.assertEqual(response.headers["cache-control"], "no-store")
        payload = jwt.decode(
            response.json()["ticket"],
            SECRET,
            algorithms=["HS256"],
            audience="face-attendance-stream",
            issuer="face-attendance",
        )
        self.assertEqual(payload["type"], "stream")
        self.assertEqual(payload["exp"] - payload["iat"], 60)

    def test_stream_ticket_cannot_authorize_data_route(self) -> None:
        ticket = self._ticket(UserRole.ADMIN)

        response = self.client.get(
            "/orgs/acme/employees",
            headers={"Authorization": f"Bearer {ticket}"},
        )

        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
