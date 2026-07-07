"""SQLite storage for employees, embeddings, and attendance events."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from face_attendance.contracts import AttendanceEvent, EmployeeRecord, FaceEmbedding


SCHEMA_VERSION = 2


class StorageError(RuntimeError):
    """Raised when storage operations fail with useful context."""


def initialize_database(database_path: str | Path) -> None:
    """Create the SQLite database and required tables if they do not exist."""

    path = Path(database_path)
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)

    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(path)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(SCHEMA_SQL)
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        connection.commit()
    except sqlite3.Error as exc:
        raise StorageError(f"failed to initialize database at {path}") from exc
    finally:
        if connection is not None:
            connection.close()


class AttendanceStorage:
    """Repository for the attendance database."""

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

    def add_employee(self, employee: EmployeeRecord) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO employees (employee_id, full_name, is_active, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    employee.employee_id,
                    employee.full_name,
                    int(employee.is_active),
                    employee.created_at.isoformat(),
                ),
            )

    def get_employee(self, employee_id: str) -> EmployeeRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT employee_id, full_name, is_active, created_at
                FROM employees
                WHERE employee_id = ?
                """,
                (employee_id,),
            ).fetchone()

        if row is None:
            return None
        return _employee_from_row(row)

    def list_employees(self) -> list[EmployeeRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT employee_id, full_name, is_active, created_at
                FROM employees
                ORDER BY employee_id
                """
            ).fetchall()
        return [_employee_from_row(row) for row in rows]

    def add_embedding(self, employee_id: str, embedding: FaceEmbedding) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO face_embeddings
                    (employee_id, model_name, dimensions, vector_json)
                VALUES (?, ?, ?, ?)
                """,
                (
                    employee_id,
                    embedding.model_name,
                    embedding.dimensions,
                    _embedding_vector_to_json(embedding.vector),
                ),
            )
            return int(cursor.lastrowid)

    def list_embeddings_for_employee(self, employee_id: str) -> list[FaceEmbedding]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT model_name, dimensions, vector_json
                FROM face_embeddings
                WHERE employee_id = ?
                ORDER BY embedding_id
                """,
                (employee_id,),
            ).fetchall()
        return [_embedding_from_row(row) for row in rows]

    def list_active_embeddings(self) -> list[tuple[str, FaceEmbedding]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT e.employee_id, f.model_name, f.dimensions, f.vector_json
                FROM face_embeddings AS f
                INNER JOIN employees AS e ON e.employee_id = f.employee_id
                WHERE e.is_active = 1
                ORDER BY e.employee_id, f.embedding_id
                """
            ).fetchall()
        return [(str(row["employee_id"]), _embedding_from_row(row)) for row in rows]

    def add_attendance_event(self, event: AttendanceEvent) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO attendance_events
                    (employee_id, occurred_at, event_type, confidence_score, match_distance)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    event.employee_id,
                    event.occurred_at.isoformat(),
                    event.event_type.value,
                    event.confidence_score,
                    event.match_distance,
                ),
            )
            return int(cursor.lastrowid)

    def list_attendance_events(self, employee_id: str | None = None) -> list[AttendanceEvent]:
        query = """
            SELECT employee_id, occurred_at, event_type, confidence_score, match_distance
            FROM attendance_events
        """
        parameters: tuple[Any, ...] = ()
        if employee_id is not None:
            query += " WHERE employee_id = ?"
            parameters = (employee_id,)
        query += " ORDER BY occurred_at, attendance_event_id"

        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [_attendance_event_from_row(row) for row in rows]

    def get_last_attendance_event(self, employee_id: str) -> AttendanceEvent | None:
        """Most recent event for an employee; drives clock-in/out toggling."""

        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT employee_id, occurred_at, event_type, confidence_score, match_distance
                FROM attendance_events
                WHERE employee_id = ?
                ORDER BY occurred_at DESC, attendance_event_id DESC
                LIMIT 1
                """,
                (employee_id,),
            ).fetchone()
        if row is None:
            return None
        return _attendance_event_from_row(row)

    def set_employee_active(self, employee_id: str, is_active: bool) -> None:
        """Activate or deactivate an employee; deactivated staff never match."""

        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE employees SET is_active = ? WHERE employee_id = ?",
                (int(is_active), employee_id),
            )
            if cursor.rowcount == 0:
                raise StorageError(f"employee {employee_id} does not exist")

    def count_employees(self, active_only: bool = False) -> int:
        query = "SELECT COUNT(*) AS total FROM employees"
        if active_only:
            query += " WHERE is_active = 1"
        with self._connect() as connection:
            row = connection.execute(query).fetchone()
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
        employee_id=str(row["employee_id"]),
        full_name=str(row["full_name"]),
        is_active=bool(row["is_active"]),
        created_at=str(row["created_at"]),
    )


def _embedding_from_row(row: sqlite3.Row) -> FaceEmbedding:
    return FaceEmbedding(
        vector=_embedding_vector_from_json(str(row["vector_json"])),
        dimensions=int(row["dimensions"]),
        model_name=str(row["model_name"]),
    )


def _attendance_event_from_row(row: sqlite3.Row) -> AttendanceEvent:
    return AttendanceEvent(
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


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS employees (
    employee_id TEXT PRIMARY KEY,
    full_name TEXT NOT NULL,
    is_active INTEGER NOT NULL CHECK (is_active IN (0, 1)),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS face_embeddings (
    embedding_id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id TEXT NOT NULL,
    model_name TEXT NOT NULL,
    dimensions INTEGER NOT NULL CHECK (dimensions > 0),
    vector_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    FOREIGN KEY (employee_id) REFERENCES employees(employee_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS attendance_events (
    attendance_event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    event_type TEXT NOT NULL CHECK (event_type IN ('clock_in', 'clock_out')),
    confidence_score REAL NOT NULL CHECK (confidence_score >= 0.0 AND confidence_score <= 1.0),
    match_distance REAL NOT NULL CHECK (match_distance >= 0.0),
    FOREIGN KEY (employee_id) REFERENCES employees(employee_id) ON DELETE RESTRICT
);

-- Hot paths at scale: per-employee event history (cooldown/toggle lookups)
-- and per-employee embedding loads for the in-memory match index.
CREATE INDEX IF NOT EXISTS idx_attendance_employee_time
    ON attendance_events(employee_id, occurred_at);
CREATE INDEX IF NOT EXISTS idx_embeddings_employee
    ON face_embeddings(employee_id);
"""
