
"""Storage package for attendance persistence."""

from face_attendance.storage.database import (
    DEFAULT_ORG_ID,
    DEFAULT_ORG_NAME,
    AttendanceStorage,
    StorageError,
    initialize_database,
    migrate_to_org_scoping,
    migrate_to_tenant_integrity,
)

__all__ = [
    "DEFAULT_ORG_ID",
    "DEFAULT_ORG_NAME",
    "AttendanceStorage",
    "StorageError",
    "initialize_database",
    "migrate_to_org_scoping",
    "migrate_to_tenant_integrity",
]
