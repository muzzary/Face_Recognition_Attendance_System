"""Command-line interface for the face-recognition attendance system.

Commands:
    init-db             create or migrate the SQLite database
    download-models     fetch the pinned ONNX models
    calibrate-liveness  measure this camera's real motion/deformation
                        range and recommend FA_LIVENESS_* settings
    enroll              enroll a new employee from the camera
    attend              run live attendance mode
    report              show recent attendance events
    employees           list, deactivate, or reactivate employees
"""

from __future__ import annotations

import argparse
import logging
import sys
import threading
from datetime import datetime, timezone

from face_attendance.app import (
    build_components,
    print_attendance_report,
    print_calibration_report,
    print_employees,
    run_attendance,
    run_enrollment,
    run_liveness_calibration,
)
from face_attendance.capture import (
    CaptureError,
    OpenCvCamera,
    open_camera_remembering_backend,
)
from face_attendance.config import AppSettings, SettingsError
from face_attendance.detection import DetectionError, YuNetDetector
from face_attendance.embeddings import EmbeddingError, EnrollmentError
from face_attendance.liveness import LivenessError
from face_attendance.matching import MatchingError
from face_attendance.model_files import ModelDownloadError, download_all_models
from face_attendance.pipeline import PipelineError
from face_attendance.storage import AttendanceStorage, StorageError, initialize_database

logger = logging.getLogger(__name__)

_EXPECTED_ERRORS = (
    SettingsError,
    CaptureError,
    DetectionError,
    EmbeddingError,
    EnrollmentError,
    LivenessError,
    MatchingError,
    ModelDownloadError,
    PipelineError,
    StorageError,
)


def _positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return number


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="face-attendance",
        description="Face-recognition attendance system",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init-db", help="create or migrate the database")

    subparsers.add_parser("download-models", help="fetch the pinned ONNX models")

    calibrate = subparsers.add_parser(
        "calibrate-liveness",
        help="measure this camera's real motion/deformation range and "
        "recommend FA_LIVENESS_* settings",
    )
    calibrate.add_argument("--camera-index", type=int, default=None)
    calibrate.add_argument(
        "--duration", type=float, default=20.0, help="seconds to record (default 20)"
    )

    enroll = subparsers.add_parser("enroll", help="enroll a new employee")
    enroll.add_argument("--employee-id", required=True, help="unique employee id")
    enroll.add_argument("--name", required=True, help="employee full name")
    enroll.add_argument("--camera-index", type=int, default=None)

    attend = subparsers.add_parser("attend", help="run live attendance mode")
    attend.add_argument("--camera-index", type=int, default=None)
    attend.add_argument(
        "--no-display",
        action="store_true",
        help="run headless (no video window); quit with Ctrl+C",
    )

    report = subparsers.add_parser("report", help="show recent attendance events")
    report.add_argument("--employee-id", default=None)
    report.add_argument("--limit", type=_positive_int, default=50)

    employees = subparsers.add_parser("employees", help="manage the roster")
    employees_sub = employees.add_subparsers(dest="employees_command", required=True)
    employees_sub.add_parser("list", help="list all employees")
    for action in ("deactivate", "activate"):
        action_parser = employees_sub.add_parser(
            action, help=f"{action} an employee (matching eligibility)"
        )
        action_parser.add_argument("--employee-id", required=True)

    return parser


def _setup_logging(settings: AppSettings) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    try:
        settings.log_dir.mkdir(parents=True, exist_ok=True)
        handlers.append(
            logging.FileHandler(settings.log_dir / "face_attendance.log", encoding="utf-8")
        )
    except OSError as exc:
        print(f"warning: file logging disabled ({exc})", file=sys.stderr)

    # force=True closes handlers from any previous main() call in the same
    # process, so repeated invocations (tests, embedding) never leak handles.
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )


def _require_models(settings: AppSettings, need_sface: bool = True) -> None:
    """Fail fast with a clear message before any camera work starts."""

    required = (
        (settings.yunet_model_path, settings.sface_model_path)
        if need_sface
        else (settings.yunet_model_path,)
    )
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise ModelDownloadError(
            "missing model files: "
            + ", ".join(missing)
            + "; run 'face-attendance download-models' first"
        )


def _make_camera(settings: AppSettings, camera_index: int | None) -> OpenCvCamera:
    index = camera_index if camera_index is not None else settings.camera_index
    # The cache lives next to the database and remembers which backend this
    # camera actually delivers frames on, so only the first launch pays the
    # auto-probe cost.
    cache_path = settings.database_path.parent / "camera_backend.json"

    print(f"Opening camera {index}...")
    # cv2.VideoCapture() is a blocking native call with no timeout knob. On
    # Windows it can silently take 30-90s when the camera hasn't been used
    # recently (the on-demand Frame Server service has to cold-start, and
    # antivirus may scan the video driver DLLs on first load). That is real
    # OS-level latency we cannot shorten - but silence during it looks
    # identical to a hang, so a background thread prints reassurance while
    # the open() call is still in flight.
    done = threading.Event()

    def _reassure() -> None:
        waited = 0
        while not done.wait(5):
            waited += 5
            print(
                f"  ...still waiting for the camera ({waited}s). This can take "
                "up to ~90s on Windows if the camera hasn't been used recently "
                "(camera service cold start); it is not stuck."
            )

    reassurance = threading.Thread(target=_reassure, daemon=True)
    reassurance.start()
    try:
        camera = open_camera_remembering_backend(
            index, settings.camera_backend, cache_path
        )
    finally:
        done.set()
    print("Camera ready.")
    return camera


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        settings = AppSettings.from_env()
        _setup_logging(settings)
        return _dispatch(args, settings)
    except _EXPECTED_ERRORS as exc:
        logger.error("%s failed: %s", args.command, exc)
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\ninterrupted")
        return 130


def _dispatch(args: argparse.Namespace, settings: AppSettings) -> int:
    if args.command == "init-db":
        initialize_database(settings.database_path)
        print(f"database ready at {settings.database_path}")
        return 0

    if args.command == "download-models":
        download_all_models(settings.models_dir)
        return 0

    if args.command == "report":
        storage = AttendanceStorage(settings.database_path)
        print_attendance_report(
            storage, settings.org_id, employee_id=args.employee_id, limit=args.limit
        )
        return 0

    if args.command == "employees":
        storage = AttendanceStorage(settings.database_path)
        if args.employees_command == "list":
            print_employees(storage, settings.org_id)
            return 0
        active = args.employees_command == "activate"
        storage.set_employee_active(settings.org_id, args.employee_id, active)
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        print(f"{args.employee_id} {'re' if active else 'de'}activated at {stamp}")
        return 0

    if args.command == "calibrate-liveness":
        _require_models(settings, need_sface=False)
        detector = YuNetDetector(
            model_path=settings.yunet_model_path,
            score_threshold=settings.detection_score_threshold,
        )
        camera = _make_camera(settings, args.camera_index)
        try:
            result = run_liveness_calibration(
                detector, camera, duration_seconds=args.duration
            )
        finally:
            camera.close()
        print_calibration_report(
            result,
            current_max_motion=settings.liveness_max_motion,
            current_min_deformation=settings.liveness_min_deformation,
        )
        return 0

    if args.command == "enroll":
        _require_models(settings)
        components = build_components(settings)
        camera = _make_camera(settings, args.camera_index)
        try:
            run_enrollment(
                components,
                camera,
                employee_id=args.employee_id,
                full_name=args.name,
            )
        finally:
            camera.close()
        return 0

    if args.command == "attend":
        _require_models(settings)
        components = build_components(settings)
        camera = _make_camera(settings, args.camera_index)
        stats = run_attendance(
            components, camera, display=not args.no_display
        )
        return 1 if stats.pipeline_failed else 0

    raise AssertionError(f"unhandled command {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
