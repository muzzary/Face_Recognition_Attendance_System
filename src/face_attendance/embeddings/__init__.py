"""Facial embedding extraction and enrollment boundary."""

from face_attendance.embeddings.base import EmbeddingError, EmbeddingExtractor
from face_attendance.embeddings.enrollment import EnrollmentError, EnrollmentService
from face_attendance.embeddings.sface import (
    SFACE_MODEL_FILENAME,
    SFACE_MODEL_NAME,
    SFaceEmbedder,
)

__all__ = [
    "EmbeddingError",
    "EmbeddingExtractor",
    "EnrollmentError",
    "EnrollmentService",
    "SFACE_MODEL_FILENAME",
    "SFACE_MODEL_NAME",
    "SFaceEmbedder",
]
