import threading
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from face_attendance.attendance_logging import AttendanceService
from face_attendance.contracts import EmployeeRecord, LivenessStatus
from face_attendance.matching import EmployeeEmbeddingIndex, EmployeeMatcher
from face_attendance.pipeline import LatestFrameSlot, PipelineError, RecognitionWorker
from face_attendance.storage import AttendanceStorage, initialize_database
from fakes import (
    RepeatingDetector,
    RepeatingEmbedder,
    ScriptedLiveness,
    make_detected_face,
    make_embedding,
    make_frame,
)

NOW = datetime(2026, 7, 7, 9, 0, tzinfo=timezone.utc)


class LatestFrameSlotTests(unittest.TestCase):
    def test_newer_frame_replaces_stale_frame(self) -> None:
        slot = LatestFrameSlot()
        slot.put(make_frame(frame_id=0))
        slot.put(make_frame(frame_id=1))
        slot.put(make_frame(frame_id=2))

        frame = slot.get(timeout=0.01)

        assert frame is not None
        self.assertEqual(frame.metadata.frame_id, 2)
        self.assertEqual(slot.dropped_count, 2)

    def test_get_after_consume_returns_none(self) -> None:
        slot = LatestFrameSlot()
        slot.put(make_frame(frame_id=0))
        slot.get(timeout=0.01)

        self.assertIsNone(slot.get(timeout=0.01))

    def test_get_wakes_up_on_put_from_other_thread(self) -> None:
        slot = LatestFrameSlot()

        def delayed_put() -> None:
            time.sleep(0.05)
            slot.put(make_frame(frame_id=9))

        threading.Thread(target=delayed_put).start()
        frame = slot.get(timeout=1.0)

        assert frame is not None
        self.assertEqual(frame.metadata.frame_id, 9)


class RecognitionWorkerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp = TemporaryDirectory()
        database_path = Path(self._temp.name) / "attendance.db"
        initialize_database(database_path)
        self.storage = AttendanceStorage(database_path)
        self.storage.add_employee(
            EmployeeRecord(employee_id="EMP-001", full_name="Ada", created_at=NOW)
        )
        self.storage.add_embedding("EMP-001", make_embedding([1.0, 0.0, 0.0]))
        self.index = EmployeeEmbeddingIndex.from_storage(self.storage)
        self.matcher = EmployeeMatcher(self.index)
        self.results = []
        self.errors = []

    def tearDown(self) -> None:
        self._temp.cleanup()

    def make_worker(
        self,
        detector,
        embedder,
        liveness=None,
        max_consecutive_errors: int = 10,
    ) -> tuple[RecognitionWorker, LatestFrameSlot]:
        slot = LatestFrameSlot()
        worker = RecognitionWorker(
            slot=slot,
            detector=detector,
            embedder=embedder,
            matcher=self.matcher,
            liveness_checker=liveness if liveness is not None else ScriptedLiveness(),
            attendance_service=AttendanceService(self.storage, cooldown_seconds=0),
            on_result=self.results.append,
            on_error=self.errors.append,
            max_consecutive_errors=max_consecutive_errors,
            poll_timeout=0.01,
        )
        return worker, slot

    def wait_for(self, predicate, timeout: float = 3.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.01)
        self.fail("condition not reached within timeout")

    def test_matched_live_face_logs_attendance(self) -> None:
        detector = RepeatingDetector([make_detected_face()])
        worker, slot = self.make_worker(detector, RepeatingEmbedder([0.99, 0.01, 0.0]))

        worker.start()
        slot.put(make_frame(frame_id=0))
        self.wait_for(lambda: len(self.results) >= 1)
        worker.stop()

        outcome = self.results[0].outcomes[0]
        self.assertTrue(outcome.match.is_match)
        assert outcome.decision is not None
        self.assertTrue(outcome.decision.logged)
        self.assertEqual(len(self.storage.list_attendance_events("EMP-001")), 1)

    def test_failed_liveness_blocks_attendance(self) -> None:
        detector = RepeatingDetector([make_detected_face()])
        worker, slot = self.make_worker(
            detector,
            RepeatingEmbedder([0.99, 0.01, 0.0]),
            liveness=ScriptedLiveness(LivenessStatus.FAILED),
        )

        worker.start()
        slot.put(make_frame(frame_id=0))
        self.wait_for(lambda: len(self.results) >= 1)
        worker.stop()

        outcome = self.results[0].outcomes[0]
        assert outcome.decision is not None
        self.assertFalse(outcome.decision.logged)
        self.assertEqual(self.storage.list_attendance_events(), [])

    def test_unknown_face_gets_no_liveness_or_decision(self) -> None:
        detector = RepeatingDetector([make_detected_face()])
        liveness = ScriptedLiveness()
        worker, slot = self.make_worker(
            detector, RepeatingEmbedder([0.0, 1.0, 0.0]), liveness=liveness
        )

        worker.start()
        slot.put(make_frame(frame_id=0))
        self.wait_for(lambda: len(self.results) >= 1)
        worker.stop()

        outcome = self.results[0].outcomes[0]
        self.assertFalse(outcome.match.is_match)
        self.assertIsNone(outcome.liveness)
        self.assertIsNone(outcome.decision)
        self.assertEqual(liveness.observed, [])

    def test_multiple_faces_in_one_frame_all_processed(self) -> None:
        faces = [make_detected_face(), make_detected_face(x=150)]
        worker, slot = self.make_worker(
            RepeatingDetector(faces), RepeatingEmbedder([0.99, 0.01, 0.0])
        )

        worker.start()
        slot.put(make_frame(frame_id=0))
        self.wait_for(lambda: len(self.results) >= 1)
        worker.stop()

        self.assertEqual(len(self.results[0].outcomes), 2)

    def test_transient_detector_error_is_reported_and_worker_recovers(self) -> None:
        detector = RepeatingDetector([make_detected_face()], failures=2)
        worker, slot = self.make_worker(detector, RepeatingEmbedder([0.99, 0.01, 0.0]))

        worker.start()
        slot.put(make_frame(frame_id=0))
        self.wait_for(lambda: len(self.errors) >= 1)
        slot.put(make_frame(frame_id=1))
        self.wait_for(lambda: len(self.errors) >= 2)
        slot.put(make_frame(frame_id=2))
        self.wait_for(lambda: len(self.results) >= 1)
        worker.stop()

        self.assertGreaterEqual(len(self.errors), 2)
        self.assertEqual(len(self.results), 1)

    def test_persistent_errors_stop_the_worker(self) -> None:
        detector = RepeatingDetector([], failures=100)
        worker, slot = self.make_worker(
            detector, RepeatingEmbedder([1.0, 0.0, 0.0]), max_consecutive_errors=3
        )

        worker.start()
        for frame_id in range(5):
            slot.put(make_frame(frame_id=frame_id))
            time.sleep(0.02)
        self.wait_for(lambda: not worker.is_alive())

        fatal = [error for error in self.errors if isinstance(error, PipelineError)]
        self.assertEqual(len(fatal), 1)
        self.assertIn("consecutive", str(fatal[0]))

    def test_stop_without_frames_exits_cleanly(self) -> None:
        worker, _ = self.make_worker(
            RepeatingDetector([]), RepeatingEmbedder([1.0, 0.0, 0.0])
        )
        worker.start()
        worker.stop()

        self.assertFalse(worker.is_alive())


if __name__ == "__main__":
    unittest.main()
