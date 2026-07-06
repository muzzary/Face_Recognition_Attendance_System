from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from face_attendance.contracts import (
    AttendanceEvent,
    AttendanceEventType,
    EmployeeRecord,
    FaceEmbedding,
)
from face_attendance.storage import AttendanceStorage, StorageError, initialize_database


NOW = datetime(2026, 7, 6, 12, 0, tzinfo=timezone.utc)


class StorageTests(unittest.TestCase):
    def test_employee_embedding_and_attendance_round_trip(self) -> None:
        with TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "attendance.db"
            initialize_database(database_path)
            storage = AttendanceStorage(database_path)

            employee = EmployeeRecord(
                employee_id="EMP-001",
                full_name="Test Employee",
                created_at=NOW,
            )
            embedding = FaceEmbedding(
                vector=[0.11, 0.22, 0.33],
                dimensions=3,
                model_name="demo-model",
            )
            event = AttendanceEvent(
                employee_id=employee.employee_id,
                occurred_at=NOW,
                event_type=AttendanceEventType.CLOCK_IN,
                confidence_score=0.91,
                match_distance=0.18,
            )

            storage.add_employee(employee)
            embedding_id = storage.add_embedding(employee.employee_id, embedding)
            event_id = storage.add_attendance_event(event)

            self.assertGreater(embedding_id, 0)
            self.assertGreater(event_id, 0)
            self.assertEqual(storage.get_employee(employee.employee_id), employee)
            self.assertEqual(storage.list_embeddings_for_employee(employee.employee_id), [embedding])
            self.assertEqual(storage.list_active_embeddings(), [(employee.employee_id, embedding)])
            self.assertEqual(storage.list_attendance_events(employee.employee_id), [event])

    def test_database_schema_has_no_raw_image_columns(self) -> None:
        with TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "attendance.db"
            initialize_database(database_path)
            storage = AttendanceStorage(database_path)

            columns_by_table = storage.list_table_columns()
            all_columns = {
                column.lower()
                for columns in columns_by_table.values()
                for column in columns
            }

            forbidden_fragments = ("image", "photo", "frame_path", "raw", "bytes")
            for column in all_columns:
                for fragment in forbidden_fragments:
                    with self.subTest(column=column, fragment=fragment):
                        self.assertNotIn(fragment, column)

    def test_foreign_keys_prevent_orphan_embeddings_and_events(self) -> None:
        with TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "attendance.db"
            initialize_database(database_path)
            storage = AttendanceStorage(database_path)
            embedding = FaceEmbedding(
                vector=[0.1],
                dimensions=1,
                model_name="demo-model",
            )
            event = AttendanceEvent(
                employee_id="EMP-404",
                occurred_at=NOW,
                event_type=AttendanceEventType.CLOCK_IN,
                confidence_score=0.8,
                match_distance=0.2,
            )

            with self.assertRaises(StorageError):
                storage.add_embedding("EMP-404", embedding)

            with self.assertRaises(StorageError):
                storage.add_attendance_event(event)

    def test_initializer_creates_parent_directory(self) -> None:
        with TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "nested" / "attendance.db"

            initialize_database(database_path)

            self.assertTrue(database_path.is_file())


if __name__ == "__main__":
    unittest.main()
