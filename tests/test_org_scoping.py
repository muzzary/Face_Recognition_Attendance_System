"""Org (tenant) scoping: isolation between orgs, the v2->v3 migration, and
loud failures when an org id is missing or unknown."""

import sqlite3
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from pydantic import ValidationError

from face_attendance.contracts import (
    AttendanceEvent,
    AttendanceEventType,
    EmployeeRecord,
    FaceEmbedding,
    UserRecord,
    UserRole,
)
from face_attendance.storage import (
    DEFAULT_ORG_ID,
    AttendanceStorage,
    StorageError,
    initialize_database,
    migrate_to_org_scoping,
    migrate_to_tenant_integrity,
)

NOW = datetime(2026, 7, 10, 9, 0, tzinfo=timezone.utc)


def _seed_org(storage: AttendanceStorage, org_id: str, employee_id: str) -> None:
    """Give an org one employee with an embedding and one attendance event."""

    storage.ensure_organization(org_id, org_id)
    storage.add_employee_with_embeddings(
        EmployeeRecord(
            org_id=org_id, employee_id=employee_id, full_name="Someone", created_at=NOW
        ),
        [FaceEmbedding(org_id=org_id, vector=[1.0, 0.0], dimensions=2, model_name="m")],
    )
    storage.add_attendance_event(
        AttendanceEvent(
            org_id=org_id,
            employee_id=employee_id,
            occurred_at=NOW,
            event_type=AttendanceEventType.CLOCK_IN,
            confidence_score=0.9,
            match_distance=0.1,
        )
    )


class OrgIsolationTests(unittest.TestCase):
    """Every read method returns only the scoped org's rows."""

    def setUp(self) -> None:
        self._temp = TemporaryDirectory()
        database_path = Path(self._temp.name) / "attendance.db"
        initialize_database(database_path)
        self.storage = AttendanceStorage(database_path)
        # Two tenants, each with an employee whose ids are globally distinct
        # (employee_id is a global primary key this phase) but whose data is
        # otherwise identical in shape.
        _seed_org(self.storage, "org-a", "EMP-A")
        _seed_org(self.storage, "org-b", "EMP-B")

    def tearDown(self) -> None:
        self._temp.cleanup()

    def test_list_employees_is_scoped(self) -> None:
        ids = [emp.employee_id for emp in self.storage.list_employees("org-a")]
        self.assertEqual(ids, ["EMP-A"])

    def test_get_employee_cannot_reach_across_orgs(self) -> None:
        self.assertIsNotNone(self.storage.get_employee("org-a", "EMP-A"))
        # EMP-B exists, but not in org-a — a cross-org lookup must miss.
        self.assertIsNone(self.storage.get_employee("org-a", "EMP-B"))

    def test_list_embeddings_for_employee_is_scoped(self) -> None:
        self.assertEqual(
            len(self.storage.list_embeddings_for_employee("org-a", "EMP-A")), 1
        )
        self.assertEqual(
            self.storage.list_embeddings_for_employee("org-a", "EMP-B"), []
        )

    def test_list_active_embeddings_is_scoped(self) -> None:
        entries = self.storage.list_active_embeddings("org-a")
        self.assertEqual([employee_id for employee_id, _ in entries], ["EMP-A"])
        self.assertEqual({emb.org_id for _, emb in entries}, {"org-a"})

    def test_list_attendance_events_is_scoped(self) -> None:
        events = self.storage.list_attendance_events("org-a")
        self.assertEqual([e.employee_id for e in events], ["EMP-A"])
        # And the employee-filtered form cannot cross orgs either.
        self.assertEqual(self.storage.list_attendance_events("org-a", "EMP-B"), [])

    def test_get_last_attendance_event_is_scoped(self) -> None:
        self.assertIsNotNone(
            self.storage.get_last_attendance_event("org-a", "EMP-A")
        )
        self.assertIsNone(
            self.storage.get_last_attendance_event("org-a", "EMP-B")
        )

    def test_count_employees_is_scoped(self) -> None:
        self.assertEqual(self.storage.count_employees("org-a"), 1)
        self.assertEqual(self.storage.count_employees("org-b"), 1)


class LoudFailureTests(unittest.TestCase):
    """Missing or unknown orgs fail loudly rather than writing silently."""

    def setUp(self) -> None:
        self._temp = TemporaryDirectory()
        database_path = Path(self._temp.name) / "attendance.db"
        initialize_database(database_path)
        self.storage = AttendanceStorage(database_path)

    def tearDown(self) -> None:
        self._temp.cleanup()

    def test_empty_org_id_is_rejected_by_the_contract(self) -> None:
        with self.assertRaises(ValidationError):
            EmployeeRecord(
                org_id="", employee_id="EMP-1", full_name="Ada", created_at=NOW
            )

    def test_writing_employee_for_unknown_org_raises(self) -> None:
        # No such organization row: the foreign key rejects the write.
        with self.assertRaises(StorageError):
            self.storage.add_employee(
                EmployeeRecord(
                    org_id="ghost-org",
                    employee_id="EMP-1",
                    full_name="Ada",
                    created_at=NOW,
                )
            )

    def test_writing_event_for_unknown_org_raises(self) -> None:
        with self.assertRaises(StorageError):
            self.storage.add_attendance_event(
                AttendanceEvent(
                    org_id="ghost-org",
                    employee_id="EMP-1",
                    occurred_at=NOW,
                    event_type=AttendanceEventType.CLOCK_IN,
                    confidence_score=0.9,
                    match_distance=0.1,
                )
            )

    def test_mixed_org_gallery_is_rejected(self) -> None:
        self.storage.ensure_organization("org-a", "org-a")
        with self.assertRaises(StorageError):
            self.storage.add_employee_with_embeddings(
                EmployeeRecord(
                    org_id="org-a",
                    employee_id="EMP-1",
                    full_name="Ada",
                    created_at=NOW,
                ),
                [FaceEmbedding(org_id="org-b", vector=[1.0], dimensions=1, model_name="m")],
            )

    def test_same_employee_id_is_allowed_in_two_orgs(self) -> None:
        for index, org_id in enumerate(("org-a", "org-b")):
            self.storage.ensure_organization(org_id, org_id)
            self.storage.add_employee_with_embeddings(
                EmployeeRecord(
                    org_id=org_id,
                    employee_id="EMP-1",
                    full_name=org_id,
                    created_at=NOW,
                ),
                [
                    FaceEmbedding(
                        org_id=org_id,
                        vector=[1.0, float(index)],
                        dimensions=2,
                        model_name="m",
                    )
                ],
            )

        self.assertEqual(self.storage.get_employee("org-a", "EMP-1").full_name, "org-a")
        self.assertEqual(self.storage.get_employee("org-b", "EMP-1").full_name, "org-b")
        self.assertEqual(
            [embedding.org_id for _, embedding in self.storage.list_active_embeddings("org-a")],
            ["org-a"],
        )
        self.assertEqual(
            [embedding.org_id for _, embedding in self.storage.list_active_embeddings("org-b")],
            ["org-b"],
        )

    def test_cross_org_embedding_relationship_is_rejected(self) -> None:
        self._seed_employee_in_org_a()
        with self.assertRaises(StorageError):
            self.storage.add_embedding(
                "EMP-1",
                FaceEmbedding(
                    org_id="org-b", vector=[1.0], dimensions=1, model_name="m"
                ),
            )

    def test_cross_org_attendance_relationship_is_rejected(self) -> None:
        self._seed_employee_in_org_a()
        with self.assertRaises(StorageError):
            self.storage.add_attendance_event(
                AttendanceEvent(
                    org_id="org-b",
                    employee_id="EMP-1",
                    occurred_at=NOW,
                    event_type=AttendanceEventType.CLOCK_IN,
                    confidence_score=0.9,
                    match_distance=0.1,
                )
            )

    def test_cross_org_employee_user_link_is_rejected(self) -> None:
        self._seed_employee_in_org_a()
        with self.assertRaises(StorageError):
            self.storage.add_user(
                UserRecord(
                    org_id="org-b",
                    user_id="employee@org-b.test",
                    role=UserRole.EMPLOYEE,
                    password_hash="test-hash",
                    employee_id="EMP-1",
                    created_at=NOW,
                )
            )

    def _seed_employee_in_org_a(self) -> None:
        self.storage.ensure_organization("org-a", "org-a")
        self.storage.ensure_organization("org-b", "org-b")
        self.storage.add_employee(
            EmployeeRecord(
                org_id="org-a",
                employee_id="EMP-1",
                full_name="Ada",
                created_at=NOW,
            )
        )


# The exact v2 schema this project shipped before org scoping, so the
# migration test runs against a realistic pre-migration database.
_V2_SCHEMA = """
CREATE TABLE employees (
    employee_id TEXT PRIMARY KEY,
    full_name TEXT NOT NULL,
    is_active INTEGER NOT NULL CHECK (is_active IN (0, 1)),
    created_at TEXT NOT NULL
);
CREATE TABLE face_embeddings (
    embedding_id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id TEXT NOT NULL,
    model_name TEXT NOT NULL,
    dimensions INTEGER NOT NULL CHECK (dimensions > 0),
    vector_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (employee_id) REFERENCES employees(employee_id) ON DELETE CASCADE
);
CREATE TABLE attendance_events (
    attendance_event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    event_type TEXT NOT NULL CHECK (event_type IN ('clock_in', 'clock_out')),
    confidence_score REAL NOT NULL CHECK (confidence_score >= 0.0 AND confidence_score <= 1.0),
    match_distance REAL NOT NULL CHECK (match_distance >= 0.0),
    FOREIGN KEY (employee_id) REFERENCES employees(employee_id) ON DELETE RESTRICT
);
CREATE INDEX idx_attendance_employee_time ON attendance_events(employee_id, occurred_at);
CREATE INDEX idx_embeddings_employee ON face_embeddings(employee_id);
"""


def _build_v2_database(path: Path) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.executescript(_V2_SCHEMA)
        connection.execute(
            "INSERT INTO employees (employee_id, full_name, is_active, created_at) "
            "VALUES ('EMP-1', 'Ada', 1, '2026-01-01T00:00:00+00:00')"
        )
        connection.execute(
            "INSERT INTO employees (employee_id, full_name, is_active, created_at) "
            "VALUES ('EMP-2', 'Bob', 0, '2026-01-02T00:00:00+00:00')"
        )
        connection.execute(
            "INSERT INTO face_embeddings "
            "(employee_id, model_name, dimensions, vector_json, created_at) "
            "VALUES ('EMP-1', 'sface', 2, '[1.0,0.0]', '2026-01-01T00:00:01+00:00')"
        )
        connection.execute(
            "INSERT INTO attendance_events "
            "(employee_id, occurred_at, event_type, confidence_score, match_distance) "
            "VALUES ('EMP-1', '2026-01-01T08:00:00+00:00', 'clock_in', 0.9, 0.1)"
        )
        connection.execute("PRAGMA user_version = 2")
        connection.commit()
    finally:
        connection.close()


_V4_SCHEMA = """
CREATE TABLE organizations (
    org_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE employees (
    employee_id TEXT PRIMARY KEY,
    full_name TEXT NOT NULL,
    is_active INTEGER NOT NULL CHECK (is_active IN (0, 1)),
    created_at TEXT NOT NULL,
    org_id TEXT NOT NULL REFERENCES organizations(org_id),
    UNIQUE (org_id, employee_id)
);
CREATE TABLE face_embeddings (
    embedding_id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id TEXT NOT NULL REFERENCES employees(employee_id) ON DELETE CASCADE,
    model_name TEXT NOT NULL,
    dimensions INTEGER NOT NULL,
    vector_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    org_id TEXT NOT NULL REFERENCES organizations(org_id)
);
CREATE TABLE attendance_events (
    attendance_event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id TEXT NOT NULL REFERENCES employees(employee_id) ON DELETE RESTRICT,
    occurred_at TEXT NOT NULL,
    event_type TEXT NOT NULL,
    confidence_score REAL NOT NULL,
    match_distance REAL NOT NULL,
    org_id TEXT NOT NULL REFERENCES organizations(org_id)
);
CREATE TABLE users (
    user_id TEXT PRIMARY KEY,
    org_id TEXT NOT NULL REFERENCES organizations(org_id),
    role TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    employee_id TEXT REFERENCES employees(employee_id),
    created_at TEXT NOT NULL
);
PRAGMA user_version = 4;
"""


def _build_v4_database(path: Path, include_cross_org_event: bool = False) -> None:
    connection = sqlite3.connect(path)
    try:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(_V4_SCHEMA)
        connection.executemany(
            "INSERT INTO organizations (org_id, name, created_at) VALUES (?, ?, ?)",
            [("org-a", "Org A", NOW.isoformat()), ("org-b", "Org B", NOW.isoformat())],
        )
        connection.execute(
            "INSERT INTO employees "
            "(employee_id, full_name, is_active, created_at, org_id) "
            "VALUES ('EMP-1', 'Ada', 1, ?, 'org-a')",
            (NOW.isoformat(),),
        )
        connection.execute(
            "INSERT INTO face_embeddings "
            "(employee_id, model_name, dimensions, vector_json, created_at, org_id) "
            "VALUES ('EMP-1', 'm', 2, '[1.0,0.0]', ?, 'org-a')",
            (NOW.isoformat(),),
        )
        event_org = "org-b" if include_cross_org_event else "org-a"
        connection.execute(
            "INSERT INTO attendance_events "
            "(employee_id, occurred_at, event_type, confidence_score, match_distance, org_id) "
            "VALUES ('EMP-1', ?, 'clock_in', 0.9, 0.1, ?)",
            (NOW.isoformat(), event_org),
        )
        connection.execute(
            "INSERT INTO users "
            "(user_id, org_id, role, password_hash, employee_id, created_at) "
            "VALUES ('employee@org-a.test', 'org-a', 'employee', 'hash', 'EMP-1', ?)",
            (NOW.isoformat(),),
        )
        connection.commit()
    finally:
        connection.close()


class TenantIntegrityMigrationTests(unittest.TestCase):
    def test_initializer_chains_v2_database_to_v5_without_data_loss(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "attendance.db"
            _build_v2_database(path)
            before = _snapshot(path)

            initialize_database(path)

            self.assertEqual(_snapshot(path), before)
            connection = sqlite3.connect(path)
            try:
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 5)
                self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
                self.assertIsNotNone(
                    connection.execute(
                        "SELECT 1 FROM sqlite_master "
                        "WHERE type = 'table' AND name = 'users'"
                    ).fetchone()
                )
            finally:
                connection.close()

    def test_initializer_migrates_v4_without_data_loss(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "attendance.db"
            _build_v4_database(path)

            initialize_database(path)
            storage = AttendanceStorage(path)

            self.assertEqual(storage.count_employees("org-a"), 1)
            self.assertEqual(len(storage.list_active_embeddings("org-a")), 1)
            self.assertEqual(len(storage.list_attendance_events("org-a")), 1)
            self.assertIsNotNone(storage.get_user_by_email("employee@org-a.test"))
            connection = sqlite3.connect(path)
            try:
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 5)
                self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
            finally:
                connection.close()

    def test_migrated_database_allows_same_employee_id_in_another_org(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "attendance.db"
            _build_v4_database(path)
            migrate_to_tenant_integrity(path)
            storage = AttendanceStorage(path)

            storage.add_employee(
                EmployeeRecord(
                    org_id="org-b",
                    employee_id="EMP-1",
                    full_name="Grace",
                    created_at=NOW,
                )
            )
            self.assertEqual(storage.get_employee("org-a", "EMP-1").full_name, "Ada")
            self.assertEqual(storage.get_employee("org-b", "EMP-1").full_name, "Grace")

    def test_migration_rolls_back_when_legacy_data_crosses_orgs(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "attendance.db"
            _build_v4_database(path, include_cross_org_event=True)

            with self.assertRaises(StorageError):
                migrate_to_tenant_integrity(path)

            connection = sqlite3.connect(path)
            try:
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 4)
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM employees").fetchone()[0], 1
                )
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM attendance_events").fetchone()[0], 1
                )
            finally:
                connection.close()


class MigrationTests(unittest.TestCase):
    def test_migration_preserves_all_rows_and_tags_default_org(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "attendance.db"
            _build_v2_database(path)

            before = _snapshot(path)

            migrate_to_org_scoping(path)

            after = _snapshot(path)
            # Old column values are byte-identical across the migration; the
            # only change is the new org_id, which is the default org.
            self.assertEqual(after["employees"], before["employees"])
            self.assertEqual(after["face_embeddings"], before["face_embeddings"])
            self.assertEqual(after["attendance_events"], before["attendance_events"])

            connection = sqlite3.connect(path)
            try:
                version = connection.execute("PRAGMA user_version").fetchone()[0]
                orgs = connection.execute(
                    "SELECT org_id, name FROM organizations"
                ).fetchall()
                emp_orgs = connection.execute(
                    "SELECT DISTINCT org_id FROM employees"
                ).fetchall()
                emb_orgs = connection.execute(
                    "SELECT DISTINCT org_id FROM face_embeddings"
                ).fetchall()
                evt_orgs = connection.execute(
                    "SELECT DISTINCT org_id FROM attendance_events"
                ).fetchall()
            finally:
                connection.close()

            self.assertEqual(version, 3)
            self.assertEqual(orgs, [(DEFAULT_ORG_ID, "Default Organization")])
            self.assertEqual(emp_orgs, [(DEFAULT_ORG_ID,)])
            self.assertEqual(emb_orgs, [(DEFAULT_ORG_ID,)])
            self.assertEqual(evt_orgs, [(DEFAULT_ORG_ID,)])

    def test_migrated_database_is_readable_through_storage(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "attendance.db"
            _build_v2_database(path)
            migrate_to_org_scoping(path)

            storage = AttendanceStorage(path)
            self.assertEqual(storage.count_employees(DEFAULT_ORG_ID), 2)
            # EMP-2 was inactive before the migration; that survives.
            active = storage.list_active_embeddings(DEFAULT_ORG_ID)
            self.assertEqual([employee_id for employee_id, _ in active], ["EMP-1"])
            events = storage.list_attendance_events(DEFAULT_ORG_ID)
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0].org_id, DEFAULT_ORG_ID)

    def test_migrating_an_already_scoped_database_raises(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "attendance.db"
            initialize_database(path)  # already v3

            with self.assertRaises(StorageError):
                migrate_to_org_scoping(path)


def _snapshot(path: Path) -> dict[str, list[tuple]]:
    """Read the pre-org columns of every table for a byte-identical compare."""

    connection = sqlite3.connect(path)
    try:
        return {
            "employees": connection.execute(
                "SELECT employee_id, full_name, is_active, created_at "
                "FROM employees ORDER BY employee_id"
            ).fetchall(),
            "face_embeddings": connection.execute(
                "SELECT embedding_id, employee_id, model_name, dimensions, "
                "vector_json, created_at FROM face_embeddings ORDER BY embedding_id"
            ).fetchall(),
            "attendance_events": connection.execute(
                "SELECT attendance_event_id, employee_id, occurred_at, event_type, "
                "confidence_score, match_distance FROM attendance_events "
                "ORDER BY attendance_event_id"
            ).fetchall(),
        }
    finally:
        connection.close()


if __name__ == "__main__":
    unittest.main()
