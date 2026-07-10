"""Dependency wiring for the read-only attendance API.

The storage instance is resolved through FastAPI's ``Depends`` so tests can
point the API at a temporary SQLite database via ``dependency_overrides``
instead of the process-wide ``FA_DATABASE_PATH``.
"""

from __future__ import annotations

from functools import lru_cache

from face_attendance.config import AppSettings
from face_attendance.storage import AttendanceStorage


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    """Load settings once from FA_* env vars (cached for the process life)."""

    return AppSettings.from_env()


def get_storage() -> AttendanceStorage:
    """Repository handle pointed at the configured database.

    Overridden in tests via ``app.dependency_overrides[get_storage]``.
    """

    return AttendanceStorage(get_settings().database_path)
