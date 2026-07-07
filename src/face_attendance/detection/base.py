"""Detection boundary: interface and errors shared by all detector adapters."""

from __future__ import annotations

from typing import Protocol

from face_attendance.capture import Frame
from face_attendance.contracts import DetectedFace


class DetectionError(RuntimeError):
    """Raised when a detector cannot load its model or process a frame."""


class FaceDetector(Protocol):
    """Detects zero or more faces in a single frame."""

    def detect(self, frame: Frame) -> list[DetectedFace]: ...
