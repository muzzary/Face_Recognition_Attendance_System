"""Camera and frame acquisition boundary."""

from face_attendance.capture.backend_cache import open_camera_remembering_backend
from face_attendance.capture.camera import (
    CAMERA_BACKENDS,
    CaptureError,
    Frame,
    FrameSource,
    OpenCvCamera,
)

__all__ = [
    "CAMERA_BACKENDS",
    "CaptureError",
    "Frame",
    "FrameSource",
    "OpenCvCamera",
    "open_camera_remembering_backend",
]
