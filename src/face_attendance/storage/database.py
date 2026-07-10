"""SQLite storage for organizations, employees, embeddings, and events."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from face_attendance.contracts import AttendanceEvent, EmployeeRecord, FaceEmbedding


SCHEMA_VERSION = 3

# Single-tenant deployments (today's CLI) all live under this organization.
# Multi-tenant callers pass their own org id everywhere instead.
DEFAULT_ORG_ID = "default"
DEFAULT_ORG_NAME = "Default Organization"


class StorageError(RuntimeError):
    """Raised when storage operations fail with useful context."""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def initialize_database(database_path: str | Path) -> None:
    """Create the SQLite database and required tables if they do not exist.

    A fresh database is created directly at the current schema version and
    seeded with the default organization so single-tenant (CLI) writes have a
    valid org to reference. Upgrading an existing v2 database is a separate,
    explicit step - see ``migrate_to_org_scoping``.
    """

    path = Path(database_path)
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)

    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(path)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(SCHEMA_SQL)
        connection.execute(
            "INSERT OR IGNORE INTO organizations (org_id, name, created_at) "
            "VALUES (?, ?, ?)",
            (DEFAULT_ORG_ID, DEFAULT_ORG_NAME, _utc_now_iso()),
        )
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        connection.commit()
    except sqlite3.Error as exc:
        raise StorageError(f"failed to initialize database at {path}") from exc
    finally:
        if connection is not None:
            connection.close()


def migrate_to_org_scoping(
    database_path: str | Path,
    default_org_id: str = DEFAULT_ORG_ID,
    default_org_name: str = DEFAULT_ORG_NAME,
) -> None:
    """Upgrade an existing v2 database in place to org-scoped schema v3.

    Adds the ``organizations`` table with one default org, then rebuilds
    ``employees``/``face_embeddings``/``attendance_events`` with a NOT NULL
    ``org_id`` (referencing organizations) and backfills every existing row
    with the default org. SQLite cannot ALTER a NOT NULL column onto a
    populated table, so each table is recreated at the target schema and its
    rows copied across with the default org id supplied for the new column.

    Foreign keys are disabled for the table swap (child tables reference
    ``employees`` by name, which the recreate would otherwise trip) and a
    ``foreign_key_check`` guards integrity before the transaction commits.
    """

    path = Path(database_path)
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(path)
        connection.isolation_level = None  # explicit BEGIN/COMMIT control

        existing_columns = [
            str(row[1])
            for row in connection.execute("PRAGMA table_info(employees)").fetchall()
        ]
        if not existing_columns:
            raise StorageError(f"no employees table at {path}; nothing to migrate")
        if "org_id" in existing_columns:
            raise StorageError(f"database at {path} is already org-scoped")

        # foreign_keys must be toggled OUTSIDE any transaction to take effect.
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute("BEGIN")

        connection.execute(_ORGANIZATIONS_TABLE)
        connection.execute(
            "INSERT OR IGNORE INTO organizations (org_id, name, created_at) "
            "VALUES (?, ?, ?)",
            (default_org_id, default_org_name, _utc_now_iso()),
        )

        connection.execute("ALTER TABLE employees RENAME TO _employees_v2")
        connection.execute("ALTER TABLE face_embeddings RENAME TO _face_embeddings_v2")
        connection.execute("ALTER TABLE attendance_events RENAME TO _attendance_events_v2")

        connection.execute(_EMPLOYEES_TABLE)
        connection.execute(_FACE_EMBEDDINGS_TABLE)
        connection.execute(_ATTENDANCE_EVENTS_TABLE)

        connection.execute(
            "INSERT INTO employees "
            "(employee_id, full_name, is_active, created_at, org_id) "
            "SELECT employee_id, full_name, is_active, created_at, ? "
            "FROM _employees_v2",
            (default_org_id,),
        )
        connection.execute(
            "INSERT INTO face_embeddings "
            "(embedding_id, employee_id, model_name, dimensions, vector_json, "
            "created_at, org_id) "
            "SELECT embedding_id, employee_id, model_name, dimensions, "
            "vector_json, created_at, ? FROM _face_embeddings_v2",
            (default_org_id,),
        )
        connection.execute(
            "INSERT INTO attendance_events "
            "(attendance_event_id, employee_id, occurred_at, event_type, "
            "confidence_score, match_distance, org_id) "
            "SELECT attendance_event_id, employee_id, occurred_at, event_type, "
            "confidence_score, match_distance, ? FROM _attendance_events_v2",
            (default_org_id,),
        )

        # Drop the old tables (freeing their index names) before recreating
        # indexes on the new tables, so the shared names never collide.
        connection.execute("DROP TABLE _attendance_events_v2")
        connection.execute("DROP TABLE _face_embeddings_v2")
        connection.execute("DROP TABLE _employees_v2")
        for statement in _INDEX_STATEMENTS:
            connection.execute(statement)

        violations = connection.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise StorageError(
                f"migration produced foreign-key violations: {violations}"
            )

        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        connection.execute("COMMIT")
        connection.execute("PRAGMA foreign_keys = ON")
    except sqlite3.Error as exc:
        if connection is not None:
            # No-op when no transaction is open (e.g. a failure during the
            # pre-migration probe), so we never mask the real error.
            connection.rollback()
        raise StorageError(f"failed to migrate database at {path}") from exc
    finally:
        if connection is not None:
            connection.close()


class AttendanceStorage:
    """Repository for the attendance database.

    Every read and write is scoped to an organization (tenant): reads filter
    by ``org_id`` and writes stamp it, so one company's data can never leak
    into another's queries.
    """

    def __init__(self, database_path: str | Path) -> None:
        self._database_path = Path(database_path)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        try:
            connection = sqlite3.connect(self._database_path, timeout=5.0)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            # WAL lets the attendance writer and report readers overlap
            # without "database is locked" errors under load.
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA busy_timeout = 5000")
            yield connection
            connection.commit()
        except sqlite3.Error as exc:
            raise StorageError(f"database operation failed for {self._database_path}") from exc
        finally:
            if "connection" in locals():
                connection.close()

    def ensure_organization(self, org_id: str, name: str) -> None:
        """Create the organization if it does not already exist (idempotent)."""

        with self._connect() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO organizations (org_id, name, created_at) "
                "VALUES (?, ?, ?)",
                (org_id, name, _utc_now_iso()),
            )

    def add_employee(self, employee: EmployeeRecord) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO employees (employee_id, full_name, is_active, created_at, org_id)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    employee.employee_id,
                    employee.full_name,
                    int(employee.is_active),
                    employee.created_at.isoformat(),
                    employee.org_id,
                ),
            )

    def get_employee(self, org_id: str, employee_id: str) -> EmployeeRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT org_id, employee_id, full_name, is_active, created_at
                FROM employees
                WHERE org_id = ? AND employee_id = ?
                """,
                (org_id, employee_id),
            ).fetchone()

        if row is None:
            return None
        return _employee_from_row(row)

    def list_employees(self, org_id: str) -> list[EmployeeRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT org_id, employee_id, full_name, is_active, created_at
                FROM employees
                WHERE org_id = ?
                ORDER BY employee_id
                """,
                (org_id,),
            ).fetchall()
        return [_employee_from_row(row) for row in rows]

    def add_employee_with_embeddings(
        self, employee: EmployeeRecord, embeddings: list[FaceEmbedding]
    ) -> None:
        """Insert an employee and their gallery in one transaction.

        Either everything lands or nothing does — a crash mid-enrollment can
        never leave an employee row with a partial (or empty) gallery.
        """

        if not embeddings:
            raise StorageError("cannot enroll an employee without embeddings")
        if any(embedding.org_id != employee.org_id for embedding in embeddings):
            raise StorageError(
                "employee and embedding org_id must match; refusing to store a "
                "gallery that mixes organizations"
            )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO employees (employee_id, full_name, is_active, created_at, org_id)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    employee.employee_id,
                    employee.full_name,
                    int(employee.is_active),
                    employee.created_at.isoformat(),
                    employee.org_id,
                ),
            )
            connection.executemany(
                """
                INSERT INTO face_embeddings
                    (employee_id, model_name, dimensions, vector_json, org_id)
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (
                        employee.employee_id,
                        embedding.model_name,
                        embedding.dimensions,
                        _embedding_vector_to_json(embedding.vector),
                        employee.org_id,
                    )
                    for embedding in embeddings
                ],
            )

    def add_embedding(self, employee_id: str, embedding: FaceEmbedding) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO face_embeddings
                    (employee_id, model_name, dimensions, vector_json, org_id)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    employee_id,
                    embedding.model_name,
                    embedding.dimensions,
                    _embedding_vector_to_json(embedding.vector),
                    embedding.org_id,
                ),
            )
            return int(cursor.lastrowid)

    def list_embeddings_for_employee(
        self, org_id: str, employee_id: str
    ) -> list[FaceEmbedding]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT org_id, model_name, dimensions, vector_json
                FROM face_embeddings
                WHERE org_id = ? AND employee_id = ?
                ORDER BY embedding_id
                """,
                (org_id, employee_id),
            ).fetchall()
        return [_embedding_from_row(row) for row in rows]

    def list_active_embeddings(self, org_id: str) -> list[tuple[str, FaceEmbedding]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT e.employee_id, f.org_id, f.model_name, f.dimensions, f.vector_json
                FROM face_embeddings AS f
                INNER JOIN employees AS e ON e.employee_id = f.employee_id
                WHERE e.is_active = 1 AND e.org_id = ?
                ORDER BY e.employee_id, f.embedding_id
                """,
                (org_id,),
            ).fetchall()
        return [(str(row["employee_id"]), _embedding_from_row(row)) for row in rows]

    def add_attendance_event(self, event: AttendanceEvent) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO attendance_events
                    (employee_id, occurred_at, event_type, confidence_score, match_distance, org_id)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    event.employee_id,
                    event.occurred_at.isoformat(),
                    event.event_type.value,
                    event.confidence_score,
                    event.match_distance,
                    event.org_id,
                ),
            )
            return int(cursor.lastrowid)

    def list_attendance_events(
        self,
        org_id: str,
        employee_id: str | None = None,
        limit: int | None = None,
    ) -> list[AttendanceEvent]:
        query = """
            SELECT org_id, employee_id, occurred_at, event_type, confidence_score, match_distance
            FROM attendance_events
            WHERE org_id = ?
        """
        parameters: tuple[Any, ...] = (org_id,)
        if employee_id is not None:
            query += " AND employee_id = ?"
            parameters = (*parameters, employee_id)
        if limit is not None:
            # Newest N via the index, then reversed to chronological order.
            query += " ORDER BY occurred_at DESC, attendance_event_id DESC LIMIT ?"
            parameters = (*parameters, int(limit))
        else:
            query += " ORDER BY occurred_at, attendance_event_id"

        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        events = [_attendance_event_from_row(row) for row in rows]
        if limit is not None:
            events.reverse()
        return events

    def get_last_attendance_event(
        self, org_id: str, employee_id: str
    ) -> AttendanceEvent | None:
        """Most recent event for an employee; drives clock-in/out toggling."""

        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT org_id, employee_id, occurred_at, event_type, confidence_score, match_distance
                FROM attendance_events
                WHERE org_id = ? AND employee_id = ?
                ORDER BY occurred_at DESC, attendance_event_id DESC
                LIMIT 1
                """,
                (org_id, employee_id),
            ).fetchone()
        if row is None:
            return None
        return _attendance_event_from_row(row)

    def set_employee_active(
        self, org_id: str, employee_id: str, is_active: bool
    ) -> None:
        """Activate or deactivate an employee; deactivated staff never match."""

        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE employees SET is_active = ? WHERE org_id = ? AND employee_id = ?",
                (int(is_active), org_id, employee_id),
            )
            if cursor.rowcount == 0:
                raise StorageError(
                    f"employee {employee_id} does not exist in org {org_id}"
                )

    def count_employees(self, org_id: str, active_only: bool = False) -> int:
        query = "SELECT COUNT(*) AS total FROM employees WHERE org_id = ?"
        if active_only:
            query += " AND is_active = 1"
        with self._connect() as connection:
            row = connection.execute(query, (org_id,)).fetchone()
        return int(row["total"])

    def list_table_columns(self) -> dict[str, list[str]]:
        """Return table columns for safety tests and lightweight diagnostics."""

        table_names = ("employees", "face_embeddings", "attendance_events")
        with self._connect() as connection:
            columns: dict[str, list[str]] = {}
            for table_name in table_names:
                _require_known_table(table_name)
                rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
                columns[table_name] = [str(row["name"]) for row in rows]
        return columns


def _employee_from_row(row: sqlite3.Row) -> EmployeeRecord:
    return EmployeeRecord(
        org_id=str(row["org_id"]),
        employee_id=str(row["employee_id"]),
        full_name=str(row["full_name"]),
        is_active=bool(row["is_active"]),
        created_at=str(row["created_at"]),
    )


def _embedding_from_row(row: sqlite3.Row) -> FaceEmbedding:
    return FaceEmbedding(
        org_id=str(row["org_id"]),
        vector=_embedding_vector_from_json(str(row["vector_json"])),
        dimensions=int(row["dimensions"]),
        model_name=str(row["model_name"]),
    )


def _attendance_event_from_row(row: sqlite3.Row) -> AttendanceEvent:
    return AttendanceEvent(
        org_id=str(row["org_id"]),
        employee_id=str(row["employee_id"]),
        occurred_at=str(row["occurred_at"]),
        event_type=str(row["event_type"]),
        confidence_score=float(row["confidence_score"]),
        match_distance=float(row["match_distance"]),
    )


def _embedding_vector_to_json(vector: list[float]) -> str:
    return json.dumps(vector, separators=(",", ":"))


def _embedding_vector_from_json(value: str) -> list[float]:
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError as exc:
        raise StorageError("stored embedding vector is not valid JSON") from exc
    if not isinstance(decoded, list):
        raise StorageError("stored embedding vector must be a JSON list")
    return [float(item) for item in decoded]


def _require_known_table(table_name: str) -> None:
    known_tables = {"employees", "face_embeddings", "attendance_events"}
    if table_name not in known_tables:
        raise StorageError(f"unknown table requested: {table_name}")


# Each table is its own constant so the fresh-schema path (executescript below)
# and the migration's table-rebuild reuse the exact same definition.
_ORGANIZATIONS_TABLE = """
CREATE TABLE IF NOT EXISTS organizations (
    org_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""

_EMPLOYEES_TABLE = """
CREATE TABLE IF NOT EXISTS employees (
    employee_id TEXT PRIMARY KEY,
    full_name TEXT NOT NULL,
    is_active INTEGER NOT NULL CHECK (is_active IN (0, 1)),
    created_at TEXT NOT NULL,
    org_id TEXT NOT NULL REFERENCES organizations(org_id),
    UNIQUE (org_id, employee_id)
);
"""

_FACE_EMBEDDINGS_TABLE = """
CREATE TABLE IF NOT EXISTS face_embeddings (
    embedding_id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id TEXT NOT NULL,
    model_name TEXT NOT NULL,
    dimensions INTEGER NOT NULL CHECK (dimensions > 0),
    vector_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    org_id TEXT NOT NULL REFERENCES organizations(org_id),
    FOREIGN KEY (employee_id) REFERENCES employees(employee_id) ON DELETE CASCADE
);
"""

_ATTENDANCE_EVENTS_TABLE = """
CREATE TABLE IF NOT EXISTS attendance_events (
    attendance_event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    event_type TEXT NOT NULL CHECK (event_type IN ('clock_in', 'clock_out')),
    confidence_score REAL NOT NULL CHECK (confidence_score >= 0.0 AND confidence_score <= 1.0),
    match_distance REAL NOT NULL CHECK (match_distance >= 0.0),
    org_id TEXT NOT NULL REFERENCES organizations(org_id),
    FOREIGN KEY (employee_id) REFERENCES employees(employee_id) ON DELETE RESTRICT
);
"""

# Hot paths at scale: per-employee event history (cooldown/toggle lookups),
# per-employee embedding loads for the match index, and per-org filtering of
# every table for tenant-scoped reports and gallery loads.
_INDEX_STATEMENTS = (
    "CREATE INDEX IF NOT EXISTS idx_attendance_employee_time "
    "ON attendance_events(employee_id, occurred_at)",
    "CREATE INDEX IF NOT EXISTS idx_embeddings_employee "
    "ON face_embeddings(employee_id)",
    "CREATE INDEX IF NOT EXISTS idx_employees_org ON employees(org_id)",
    "CREATE INDEX IF NOT EXISTS idx_embeddings_org ON face_embeddings(org_id)",
    "CREATE INDEX IF NOT EXISTS idx_attendance_org ON attendance_events(org_id)",
)

SCHEMA_SQL = (
    _ORGANIZATIONS_TABLE
    + _EMPLOYEES_TABLE
    + _FACE_EMBEDDINGS_TABLE
    + _ATTENDANCE_EVENTS_TABLE
    + "\n"
    + ";\n".join(_INDEX_STATEMENTS)
    + ";\n"
)
