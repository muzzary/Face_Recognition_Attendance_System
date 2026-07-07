"""Threshold decision layer that turns similarity scores into MatchResults."""

from __future__ import annotations

from face_attendance.contracts import FaceEmbedding, MatchResult
from face_attendance.matching.index import EmployeeEmbeddingIndex

# OpenCV's published cosine-similarity threshold for SFace: scores >= 0.363
# indicate the same identity. Documented with rationale in the README.
DEFAULT_SIMILARITY_THRESHOLD = 0.363


class EmployeeMatcher:
    """Compares a live embedding against the gallery and applies the threshold."""

    def __init__(
        self,
        index: EmployeeEmbeddingIndex,
        similarity_threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
    ) -> None:
        if not -1.0 < similarity_threshold < 1.0:
            raise ValueError("similarity_threshold must be in (-1, 1)")
        self._index = index
        self._similarity_threshold = similarity_threshold

    @property
    def similarity_threshold(self) -> float:
        return self._similarity_threshold

    def match(self, probe: FaceEmbedding) -> MatchResult:
        best = self._index.best_match(probe)
        distance_threshold = 1.0 - self._similarity_threshold

        if best is None:
            # Empty gallery: report an explicit non-match at maximum distance.
            return MatchResult(
                is_match=False,
                distance=2.0,
                threshold=distance_threshold,
                confidence_score=0.0,
            )

        employee_id, similarity = best
        is_match = similarity >= self._similarity_threshold
        return MatchResult(
            is_match=is_match,
            employee_id=employee_id if is_match else None,
            distance=max(0.0, 1.0 - similarity),
            threshold=distance_threshold,
            confidence_score=_similarity_to_confidence(similarity),
        )


def _similarity_to_confidence(similarity: float) -> float:
    """Map cosine similarity [-1, 1] to a bounded confidence score [0, 1]."""

    return min(1.0, max(0.0, (similarity + 1.0) / 2.0))
