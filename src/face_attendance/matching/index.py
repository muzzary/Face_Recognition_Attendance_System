"""In-memory embedding index for O(1)-latency matching at 1000+ employees.

All enrolled embeddings live in one L2-normalized numpy matrix, so matching a
live face is a single matrix-vector product (~5000x128 floats for 1000
employees with 5 samples each — well under a millisecond) instead of a
per-employee database query.
"""

from __future__ import annotations

import threading

import numpy as np

from face_attendance.contracts import FaceEmbedding
from face_attendance.matching.similarity import SimilarityError, normalize_rows
from face_attendance.storage import DEFAULT_ORG_ID, AttendanceStorage


class MatchingError(RuntimeError):
    """Raised when the index cannot be built or a probe cannot be compared."""


class EmployeeEmbeddingIndex:
    """Thread-safe snapshot of all active employees' embeddings."""

    def __init__(
        self,
        entries: list[tuple[str, FaceEmbedding]],
        org_id: str = DEFAULT_ORG_ID,
    ) -> None:
        self._lock = threading.Lock()
        self._org_id = org_id
        self._employee_ids: list[str] = []
        self._matrix: np.ndarray | None = None
        self._dimensions: int | None = None
        self._swap(_build_snapshot(entries))

    @classmethod
    def from_storage(
        cls, storage: AttendanceStorage, org_id: str = DEFAULT_ORG_ID
    ) -> EmployeeEmbeddingIndex:
        return cls(storage.list_active_embeddings(org_id), org_id)

    def refresh_from_storage(self, storage: AttendanceStorage) -> None:
        """Rebuild the snapshot after enrollments or deactivations.

        The new snapshot is built fully before the swap, so a failed rebuild
        (bad data in storage) raises and leaves the last good gallery serving.
        Stays scoped to this index's org, so a refresh never pulls in another
        tenant's employees.
        """

        snapshot = _build_snapshot(storage.list_active_embeddings(self._org_id))
        self._swap(snapshot)

    def _swap(
        self, snapshot: tuple[list[str], np.ndarray | None, int | None]
    ) -> None:
        employee_ids, matrix, dimensions = snapshot
        with self._lock:
            self._employee_ids = employee_ids
            self._matrix = matrix
            self._dimensions = dimensions

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._employee_ids)

    @property
    def employee_count(self) -> int:
        with self._lock:
            return len(set(self._employee_ids))

    def best_match(self, probe: FaceEmbedding) -> tuple[str, float] | None:
        """Return (employee_id, cosine_similarity) of the closest gallery entry."""

        with self._lock:
            matrix = self._matrix
            employee_ids = self._employee_ids
            dimensions = self._dimensions

        if matrix is None or not employee_ids:
            return None
        if probe.dimensions != dimensions:
            raise MatchingError(
                f"probe embedding has {probe.dimensions} dimensions, "
                f"index expects {dimensions}"
            )

        vector = np.asarray(probe.vector, dtype=np.float64)
        norm = float(np.linalg.norm(vector))
        if norm == 0.0:
            raise MatchingError("probe embedding has zero magnitude")

        similarities = matrix @ (vector / norm)
        best_row = int(np.argmax(similarities))
        return employee_ids[best_row], float(similarities[best_row])


def _build_snapshot(
    entries: list[tuple[str, FaceEmbedding]],
) -> tuple[list[str], np.ndarray | None, int | None]:
    """Validate entries and build the normalized matrix, without touching state."""

    if not entries:
        return [], None, None

    dimensions = entries[0][1].dimensions
    vectors: list[list[float]] = []
    employee_ids: list[str] = []
    for employee_id, embedding in entries:
        if embedding.dimensions != dimensions:
            raise MatchingError(
                "embedding dimensions are inconsistent in storage: "
                f"{embedding.dimensions} vs {dimensions} "
                f"(employee {employee_id}); re-enroll with one model"
            )
        employee_ids.append(employee_id)
        vectors.append(embedding.vector)

    try:
        matrix = normalize_rows(np.asarray(vectors, dtype=np.float64))
    except SimilarityError as exc:
        raise MatchingError("storage contains a zero-magnitude embedding") from exc
    return employee_ids, matrix, dimensions
