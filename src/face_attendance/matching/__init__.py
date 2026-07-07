"""Employee matching boundary."""

from face_attendance.matching.index import EmployeeEmbeddingIndex, MatchingError
from face_attendance.matching.matcher import (
    DEFAULT_SIMILARITY_THRESHOLD,
    EmployeeMatcher,
)
from face_attendance.matching.similarity import (
    SimilarityError,
    cosine_similarity,
    normalize_rows,
)

__all__ = [
    "DEFAULT_SIMILARITY_THRESHOLD",
    "EmployeeEmbeddingIndex",
    "EmployeeMatcher",
    "MatchingError",
    "SimilarityError",
    "cosine_similarity",
    "normalize_rows",
]
