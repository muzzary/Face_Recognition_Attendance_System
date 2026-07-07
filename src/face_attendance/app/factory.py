"""Builds the wired pipeline components from validated settings."""

from __future__ import annotations

from dataclasses import dataclass

from face_attendance.attendance_logging import AttendanceService
from face_attendance.config import AppSettings
from face_attendance.detection import YuNetDetector
from face_attendance.detection.base import FaceDetector
from face_attendance.embeddings import EnrollmentService, SFaceEmbedder
from face_attendance.embeddings.base import EmbeddingExtractor
from face_attendance.liveness import MicroMovementLivenessChecker
from face_attendance.matching import EmployeeEmbeddingIndex, EmployeeMatcher
from face_attendance.storage import AttendanceStorage, initialize_database


@dataclass
class PipelineComponents:
    """Everything the enrollment and attendance flows need, pre-wired."""

    settings: AppSettings
    storage: AttendanceStorage
    detector: FaceDetector
    embedder: EmbeddingExtractor
    index: EmployeeEmbeddingIndex
    matcher: EmployeeMatcher
    liveness: MicroMovementLivenessChecker
    attendance: AttendanceService
    enrollment: EnrollmentService


def build_components(settings: AppSettings) -> PipelineComponents:
    """Initialize storage and construct the full pipeline from settings.

    Model files are validated lazily (on first frame), so building components
    is cheap and works before models are downloaded — commands that do not
    touch the camera (report, list) stay usable either way.
    """

    initialize_database(settings.database_path)
    storage = AttendanceStorage(settings.database_path)

    detector = YuNetDetector(
        model_path=settings.yunet_model_path,
        score_threshold=settings.detection_score_threshold,
    )
    embedder = SFaceEmbedder(model_path=settings.sface_model_path)
    index = EmployeeEmbeddingIndex.from_storage(storage)
    matcher = EmployeeMatcher(index, similarity_threshold=settings.similarity_threshold)
    liveness = MicroMovementLivenessChecker(
        window_size=settings.liveness_window_size,
        min_motion=settings.liveness_min_motion,
        min_deformation=settings.liveness_min_deformation,
        max_frame_gap=settings.liveness_max_frame_gap,
    )
    attendance = AttendanceService(storage, cooldown_seconds=settings.cooldown_seconds)
    enrollment = EnrollmentService(
        detector=detector,
        embedder=embedder,
        storage=storage,
        min_detection_confidence=settings.enrollment_min_confidence,
        min_face_size=settings.enrollment_min_face_size,
        required_samples=settings.enrollment_samples,
    )

    return PipelineComponents(
        settings=settings,
        storage=storage,
        detector=detector,
        embedder=embedder,
        index=index,
        matcher=matcher,
        liveness=liveness,
        attendance=attendance,
        enrollment=enrollment,
    )
