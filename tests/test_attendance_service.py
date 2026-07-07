import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from face_attendance.attendance_logging import AttendanceService
from face_attendance.contracts import (
    AttendanceEventType,
    EmployeeRecord,
    LivenessResult,
    LivenessStatus,
    MatchResult,
)
from face_attendance.storage import AttendanceStorage, initialize_database

NOW = datetime(2026, 7, 7, 9, 0, tzinfo=timezone.utc)


def passed_liveness() -> LivenessResult:
    return LivenessResult(
        status=LivenessStatus.PASSED,
        method="micro-movement",
        frame_count=12,
        confidence_score=0.9,
    )


def failed_liveness(reason: str = "static frames") -> LivenessResult:
    return LivenessResult(
        status=LivenessStatus.FAILED,
        method="micro-movement",
        frame_count=12,
        confidence_score=0.2,
        reason=reason,
    )


def good_match(employee_id: str = "EMP-001") -> MatchResult:
    return MatchResult(
        is_match=True,
        employee_id=employee_id,
        distance=0.3,
        threshold=0.637,
        confidence_score=0.85,
    )


class AttendanceServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = TemporaryDirectory()
        database_path = Path(self._temp.name) / "attendance.db"
        initialize_database(database_path)
        self.storage = AttendanceStorage(database_path)
        self.storage.add_employee(
            EmployeeRecord(employee_id="EMP-001", full_name="Ada", created_at=NOW)
        )
        self.service = AttendanceService(self.storage, cooldown_seconds=60)

    def tearDown(self) -> None:
        self._temp.cleanup()

    def test_first_event_is_clock_in(self) -> None:
        decision = self.service.record(good_match(), passed_liveness(), now=NOW)

        self.assertTrue(decision.logged)
        assert decision.event is not None
        self.assertEqual(decision.event.event_type, AttendanceEventType.CLOCK_IN)
        self.assertEqual(len(self.storage.list_attendance_events("EMP-001")), 1)

    def test_second_event_after_cooldown_is_clock_out(self) -> None:
        self.service.record(good_match(), passed_liveness(), now=NOW)

        later = NOW + timedelta(minutes=5)
        decision = self.service.record(good_match(), passed_liveness(), now=later)

        assert decision.event is not None
        self.assertEqual(decision.event.event_type, AttendanceEventType.CLOCK_OUT)

    def test_cooldown_suppresses_duplicate_events(self) -> None:
        self.service.record(good_match(), passed_liveness(), now=NOW)

        decision = self.service.record(
            good_match(), passed_liveness(), now=NOW + timedelta(seconds=10)
        )

        self.assertFalse(decision.logged)
        self.assertIn("cooldown", decision.reason)
        self.assertEqual(len(self.storage.list_attendance_events("EMP-001")), 1)

    def test_unmatched_face_never_logs(self) -> None:
        no_match = MatchResult(
            is_match=False, distance=0.9, threshold=0.637, confidence_score=0.4
        )

        decision = self.service.record(no_match, passed_liveness(), now=NOW)

        self.assertFalse(decision.logged)
        self.assertEqual(self.storage.list_attendance_events(), [])

    def test_failed_liveness_never_logs(self) -> None:
        decision = self.service.record(good_match(), failed_liveness(), now=NOW)

        self.assertFalse(decision.logged)
        self.assertIn("liveness", decision.reason)
        self.assertEqual(self.storage.list_attendance_events(), [])

    def test_event_records_required_fields(self) -> None:
        decision = self.service.record(good_match(), passed_liveness(), now=NOW)

        assert decision.event is not None
        stored = self.storage.list_attendance_events("EMP-001")[0]
        self.assertEqual(stored.employee_id, "EMP-001")
        self.assertEqual(stored.occurred_at, NOW)
        self.assertEqual(stored.event_type, AttendanceEventType.CLOCK_IN)
        self.assertEqual(stored.confidence_score, 0.85)
        self.assertEqual(stored.match_distance, 0.3)

    def test_naive_timestamp_rejected(self) -> None:
        from face_attendance.attendance_logging import AttendanceError

        with self.assertRaises(AttendanceError):
            self.service.record(
                good_match(), passed_liveness(), now=datetime(2026, 7, 7, 9, 0)
            )


class StorageUpgradeTests(unittest.TestCase):
    def test_last_event_lookup_and_deactivation(self) -> None:
        with TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "attendance.db"
            initialize_database(database_path)
            storage = AttendanceStorage(database_path)
            storage.add_employee(
                EmployeeRecord(employee_id="EMP-001", full_name="Ada", created_at=NOW)
            )

            self.assertIsNone(storage.get_last_attendance_event("EMP-001"))
            self.assertEqual(storage.count_employees(active_only=True), 1)

            storage.set_employee_active("EMP-001", False)
            self.assertEqual(storage.count_employees(active_only=True), 0)
            self.assertEqual(storage.count_employees(), 1)
            self.assertEqual(storage.list_active_embeddings(), [])

    def test_atomic_enrollment_round_trip(self) -> None:
        from fakes import make_embedding

        with TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "attendance.db"
            initialize_database(database_path)
            storage = AttendanceStorage(database_path)
            employee = EmployeeRecord(
                employee_id="EMP-001", full_name="Ada", created_at=NOW
            )
            samples = [make_embedding([1.0, 0.0]), make_embedding([0.9, 0.1])]

            storage.add_employee_with_embeddings(employee, samples)

            self.assertEqual(storage.get_employee("EMP-001"), employee)
            self.assertEqual(
                storage.list_embeddings_for_employee("EMP-001"), samples
            )

    def test_atomic_enrollment_leaves_nothing_on_failure(self) -> None:
        from face_attendance.storage import StorageError
        from fakes import make_embedding

        with TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "attendance.db"
            initialize_database(database_path)
            storage = AttendanceStorage(database_path)
            employee = EmployeeRecord(
                employee_id="EMP-001", full_name="Ada", created_at=NOW
            )
            storage.add_employee_with_embeddings(employee, [make_embedding()])

            # Duplicate id fails; the whole transaction must roll back.
            with self.assertRaises(StorageError):
                storage.add_employee_with_embeddings(
                    employee, [make_embedding(), make_embedding()]
                )
            self.assertEqual(
                len(storage.list_embeddings_for_employee("EMP-001")), 1
            )

            with self.assertRaises(StorageError):
                storage.add_employee_with_embeddings(
                    EmployeeRecord(
                        employee_id="EMP-002", full_name="Bob", created_at=NOW
                    ),
                    [],
                )
            self.assertIsNone(storage.get_employee("EMP-002"))

    def test_index_refresh_drops_deactivated_employee(self) -> None:
        from face_attendance.matching import EmployeeEmbeddingIndex
        from fakes import make_embedding

        with TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "attendance.db"
            initialize_database(database_path)
            storage = AttendanceStorage(database_path)
            storage.add_employee_with_embeddings(
                EmployeeRecord(employee_id="EMP-001", full_name="Ada", created_at=NOW),
                [make_embedding([1.0, 0.0])],
            )
            index = EmployeeEmbeddingIndex.from_storage(storage)
            self.assertIsNotNone(index.best_match(make_embedding([1.0, 0.0])))

            storage.set_employee_active("EMP-001", False)
            index.refresh_from_storage(storage)

            self.assertIsNone(index.best_match(make_embedding([1.0, 0.0])))

    def test_deactivating_missing_employee_raises(self) -> None:
        from face_attendance.storage import StorageError

        with TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / "attendance.db"
            initialize_database(database_path)
            storage = AttendanceStorage(database_path)

            with self.assertRaises(StorageError):
                storage.set_employee_active("EMP-404", True)


if __name__ == "__main__":
    unittest.main()
