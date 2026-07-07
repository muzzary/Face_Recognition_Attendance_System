import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from face_attendance.app import (
    PipelineComponents,
    run_attendance,
    run_enrollment,
)
from face_attendance.attendance_logging import AttendanceService
from face_attendance.cli import main
from face_attendance.config import AppSettings
from face_attendance.contracts import EmployeeRecord
from face_attendance.embeddings import EnrollmentError, EnrollmentService
from face_attendance.liveness import MicroMovementLivenessChecker
from face_attendance.matching import EmployeeEmbeddingIndex, EmployeeMatcher
from face_attendance.storage import AttendanceStorage, initialize_database
from fakes import (
    FakeFrameSource,
    RepeatingDetector,
    RepeatingEmbedder,
    ScriptedLiveness,
    make_detected_face,
    make_embedding,
    make_frame,
)

NOW = datetime(2026, 7, 7, 9, 0, tzinfo=timezone.utc)


def build_fake_components(
    temp_dir: str,
    detector,
    embedder,
    liveness=None,
    enrollment_samples: int = 2,
) -> PipelineComponents:
    settings = AppSettings.from_env(
        environ={
            "FA_DATABASE_PATH": str(Path(temp_dir) / "attendance.db"),
            "FA_ENROLLMENT_SAMPLES": str(enrollment_samples),
            "FA_ENROLLMENT_FRAME_GAP": "0",
            "FA_COOLDOWN_SECONDS": "0",
        }
    )
    initialize_database(settings.database_path)
    storage = AttendanceStorage(settings.database_path)
    index = EmployeeEmbeddingIndex.from_storage(storage)
    return PipelineComponents(
        settings=settings,
        storage=storage,
        detector=detector,
        embedder=embedder,
        index=index,
        matcher=EmployeeMatcher(index),
        liveness=liveness if liveness is not None else ScriptedLiveness(),
        attendance=AttendanceService(storage, cooldown_seconds=0),
        enrollment=EnrollmentService(
            detector=detector,
            embedder=embedder,
            storage=storage,
            required_samples=enrollment_samples,
        ),
    )


def open_source(frames, read_delay: float = 0.0) -> FakeFrameSource:
    source = FakeFrameSource(frames, read_delay=read_delay)
    source.open()
    return source


class EnrollmentFlowTests(unittest.TestCase):
    def test_enrollment_end_to_end_with_fakes(self) -> None:
        with TemporaryDirectory() as temp_dir:
            components = build_fake_components(
                temp_dir,
                detector=RepeatingDetector([make_detected_face()]),
                embedder=RepeatingEmbedder([0.9, 0.1, 0.0]),
            )
            frames = [make_frame(frame_id=i) for i in range(10)]
            messages: list[str] = []

            employee = run_enrollment(
                components,
                open_source(frames),
                employee_id="EMP-001",
                full_name="Ada Lovelace",
                on_message=messages.append,
            )

            self.assertEqual(employee.employee_id, "EMP-001")
            self.assertEqual(
                len(components.storage.list_embeddings_for_employee("EMP-001")), 2
            )
            # Index refreshed: the new employee is immediately matchable.
            self.assertEqual(components.index.size, 2)
            self.assertTrue(any("Enrolled" in message for message in messages))

    def test_enrollment_fails_when_frames_run_out(self) -> None:
        with TemporaryDirectory() as temp_dir:
            components = build_fake_components(
                temp_dir,
                detector=RepeatingDetector([]),  # never sees a face
                embedder=RepeatingEmbedder([0.9, 0.1, 0.0]),
            )
            frames = [make_frame(frame_id=i) for i in range(5)]

            with self.assertRaises(EnrollmentError) as ctx:
                run_enrollment(
                    components,
                    open_source(frames),
                    employee_id="EMP-001",
                    full_name="Ada",
                    on_message=lambda _: None,
                    max_frames=5,
                )
            self.assertIn("could not capture", str(ctx.exception))

    def test_duplicate_enrollment_rejected_before_camera_work(self) -> None:
        with TemporaryDirectory() as temp_dir:
            components = build_fake_components(
                temp_dir,
                detector=RepeatingDetector([make_detected_face()]),
                embedder=RepeatingEmbedder([0.9, 0.1, 0.0]),
            )
            components.storage.add_employee(
                EmployeeRecord(employee_id="EMP-001", full_name="Ada", created_at=NOW)
            )

            with self.assertRaises(EnrollmentError) as ctx:
                run_enrollment(
                    components,
                    open_source([make_frame()]),
                    employee_id="EMP-001",
                    full_name="Ada",
                    on_message=lambda _: None,
                )
            self.assertIn("already enrolled", str(ctx.exception))


class AttendanceFlowTests(unittest.TestCase):
    def test_attendance_end_to_end_logs_events(self) -> None:
        with TemporaryDirectory() as temp_dir:
            components = build_fake_components(
                temp_dir,
                detector=RepeatingDetector([make_detected_face()]),
                embedder=RepeatingEmbedder([1.0, 0.0, 0.0]),
            )
            components.storage.add_employee(
                EmployeeRecord(employee_id="EMP-001", full_name="Ada", created_at=NOW)
            )
            components.storage.add_embedding("EMP-001", make_embedding([1.0, 0.0, 0.0]))
            components.index.refresh_from_storage(components.storage)

            frames = [make_frame(frame_id=i) for i in range(150)]
            messages: list[str] = []
            stats = run_attendance(
                components,
                open_source(frames, read_delay=0.002),
                display=False,
                on_message=messages.append,
                max_frames=150,
            )

            self.assertGreaterEqual(stats.events_logged, 1)
            self.assertFalse(stats.pipeline_failed)
            events = components.storage.list_attendance_events("EMP-001")
            self.assertGreaterEqual(len(events), 1)
            self.assertTrue(any("CLOCK_IN" in message for message in messages))

    def test_attendance_with_empty_gallery_warns_and_logs_nothing(self) -> None:
        with TemporaryDirectory() as temp_dir:
            components = build_fake_components(
                temp_dir,
                detector=RepeatingDetector([make_detected_face()]),
                embedder=RepeatingEmbedder([1.0, 0.0, 0.0]),
            )
            frames = [make_frame(frame_id=i) for i in range(20)]
            messages: list[str] = []

            stats = run_attendance(
                components,
                open_source(frames, read_delay=0.002),
                display=False,
                on_message=messages.append,
                max_frames=20,
            )

            self.assertEqual(stats.events_logged, 0)
            self.assertTrue(any("no enrolled employees" in m for m in messages))
            self.assertEqual(components.storage.list_attendance_events(), [])


class CliTests(unittest.TestCase):
    def run_cli(self, args: list[str], temp_dir: str) -> int:
        # Logs go outside temp_dir: the root logger keeps the log file open,
        # which would break TemporaryDirectory cleanup on Windows.
        env = {
            "FA_DATABASE_PATH": str(Path(temp_dir) / "cli.db"),
            "FA_LOG_DIR": str(Path(tempfile.gettempdir()) / "fa-cli-test-logs"),
        }
        with patch.dict(os.environ, env):
            return main(args)

    def test_init_db_creates_database(self) -> None:
        with TemporaryDirectory() as temp_dir:
            exit_code = self.run_cli(["init-db"], temp_dir)

            self.assertEqual(exit_code, 0)
            self.assertTrue((Path(temp_dir) / "cli.db").is_file())

    def test_report_on_empty_database(self) -> None:
        with TemporaryDirectory() as temp_dir:
            self.run_cli(["init-db"], temp_dir)

            self.assertEqual(self.run_cli(["report"], temp_dir), 0)

    def test_employees_list_and_deactivate_missing(self) -> None:
        with TemporaryDirectory() as temp_dir:
            self.run_cli(["init-db"], temp_dir)

            self.assertEqual(self.run_cli(["employees", "list"], temp_dir), 0)
            self.assertEqual(
                self.run_cli(
                    ["employees", "deactivate", "--employee-id", "EMP-404"], temp_dir
                ),
                1,
            )

    def test_unknown_command_exits_with_usage_error(self) -> None:
        with TemporaryDirectory() as temp_dir:
            with self.assertRaises(SystemExit):
                self.run_cli(["frobnicate"], temp_dir)


if __name__ == "__main__":
    unittest.main()
