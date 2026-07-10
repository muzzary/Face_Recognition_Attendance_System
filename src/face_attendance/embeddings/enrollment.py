"""Employee enrollment: capture quality-checked samples, store embeddings only."""

from __future__ import annotations

from datetime import datetime, timezone
from itertools import combinations

from face_attendance.capture import Frame
from face_attendance.contracts import DetectedFace, EmployeeRecord, FaceEmbedding
from face_attendance.detection.base import FaceDetector
from face_attendance.embeddings.base import EmbeddingExtractor
from face_attendance.matching.similarity import cosine_similarity
from face_attendance.storage import DEFAULT_ORG_ID, AttendanceStorage


class EnrollmentError(RuntimeError):
    """Raised when an enrollment sample or the overall enrollment is invalid."""


class EnrollmentService:
    """Collects embedding samples for a new employee with quality gates.

    Quality gates keep the gallery clean, which matters at scale: one bad
    enrollment photo degrades matching for that employee and increases the
    false-accept surface for everyone else.
    """

    def __init__(
        self,
        detector: FaceDetector,
        embedder: EmbeddingExtractor,
        storage: AttendanceStorage,
        org_id: str = DEFAULT_ORG_ID,
        min_detection_confidence: float = 0.85,
        min_face_size: int = 80,
        required_samples: int = 5,
        min_pairwise_similarity: float = 0.4,
    ) -> None:
        if required_samples < 1:
            raise ValueError("required_samples must be >= 1")
        self._detector = detector
        self._embedder = embedder
        self._storage = storage
        self._org_id = org_id
        self._min_detection_confidence = min_detection_confidence
        self._min_face_size = min_face_size
        self._required_samples = required_samples
        self._min_pairwise_similarity = min_pairwise_similarity

    @property
    def required_samples(self) -> int:
        return self._required_samples

    def capture_sample(self, frame: Frame) -> FaceEmbedding:
        """Extract one enrollment-quality embedding from a frame."""

        faces = self._detector.detect(frame)
        if not faces:
            raise EnrollmentError("no face detected; face the camera directly")
        if len(faces) > 1:
            raise EnrollmentError(
                f"{len(faces)} faces detected; enrollment requires exactly one person in frame"
            )

        face = faces[0]
        self._require_quality(face)
        return self._embedder.extract(frame, face)

    def enroll(
        self,
        employee_id: str,
        full_name: str,
        samples: list[FaceEmbedding],
    ) -> EmployeeRecord:
        """Validate samples as a set and persist the employee with embeddings."""

        if len(samples) < self._required_samples:
            raise EnrollmentError(
                f"need {self._required_samples} samples, got {len(samples)}"
            )
        self._require_consistency(samples)

        if self._storage.get_employee(self._org_id, employee_id) is not None:
            raise EnrollmentError(f"employee {employee_id} is already enrolled")

        employee = EmployeeRecord(
            org_id=self._org_id,
            employee_id=employee_id,
            full_name=full_name,
            created_at=datetime.now(timezone.utc),
        )
        # Single transaction: a crash mid-enrollment leaves no partial gallery.
        self._storage.add_employee_with_embeddings(employee, samples)
        return employee

    def _require_quality(self, face: DetectedFace) -> None:
        if face.detection_confidence < self._min_detection_confidence:
            raise EnrollmentError(
                "face detection confidence "
                f"{face.detection_confidence:.2f} is below the enrollment minimum "
                f"{self._min_detection_confidence:.2f}; improve lighting or move closer"
            )
        box = face.bounding_box
        if box.width < self._min_face_size or box.height < self._min_face_size:
            raise EnrollmentError(
                f"face is too small ({box.width}x{box.height}px); "
                f"move closer so the face is at least {self._min_face_size}px"
            )

    def _require_consistency(self, samples: list[FaceEmbedding]) -> None:
        """Reject sample sets that disagree with each other.

        Low pairwise similarity usually means a second person walked into a
        sample or a capture was corrupted mid-enrollment.
        """

        for index_a, index_b in combinations(range(len(samples)), 2):
            similarity = cosine_similarity(
                samples[index_a].vector, samples[index_b].vector
            )
            if similarity < self._min_pairwise_similarity:
                raise EnrollmentError(
                    f"samples {index_a} and {index_b} are inconsistent "
                    f"(similarity {similarity:.2f} < {self._min_pairwise_similarity:.2f}); "
                    "restart enrollment with only the employee in frame"
                )
