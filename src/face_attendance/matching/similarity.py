"""Cosine similarity helpers shared by enrollment checks and matching."""

from __future__ import annotations

import numpy as np


class SimilarityError(ValueError):
    """Raised when vectors cannot be compared."""


def normalize_rows(matrix: np.ndarray) -> np.ndarray:
    """L2-normalize each row; zero rows raise instead of dividing by zero."""

    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    if np.any(norms == 0.0):
        raise SimilarityError("cannot normalize a zero-magnitude embedding vector")
    return matrix / norms


def cosine_similarity(first: list[float], second: list[float]) -> float:
    a = np.asarray(first, dtype=np.float64)
    b = np.asarray(second, dtype=np.float64)
    if a.shape != b.shape:
        raise SimilarityError(
            f"embedding dimensions differ: {a.shape[0]} vs {b.shape[0]}"
        )
    norm_a = float(np.linalg.norm(a))
    norm_b = float(np.linalg.norm(b))
    if norm_a == 0.0 or norm_b == 0.0:
        raise SimilarityError("cannot compare a zero-magnitude embedding vector")
    return float(np.dot(a, b) / (norm_a * norm_b))
