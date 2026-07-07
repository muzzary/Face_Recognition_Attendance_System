"""Embedding boundary: interface and errors shared by all embedder adapters."""

from __future__ import annotations

from typing import Protocol

from face_attendance.capture import Frame
from face_attendance.contracts import DetectedFace, FaceEmbedding


class EmbeddingError(RuntimeError):
    """Raised when an embedding model cannot load or process a face."""


class EmbeddingExtractor(Protocol):
    """Turns a detected face in a frame into a numeric embedding vector."""

    @property
    def model_name(self) -> str: ...

    def extract(self, frame: Frame, face: DetectedFace) -> FaceEmbedding: ...
