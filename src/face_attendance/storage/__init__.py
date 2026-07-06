
"""Storage package for attendance persistence."""

from face_attendance.storage.database import (
    AttendanceStorage,
    StorageError,
    initialize_database,
)

__all__ = ["AttendanceStorage", "StorageError", "initialize_database"]
