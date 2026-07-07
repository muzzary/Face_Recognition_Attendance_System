"""Camera and frame acquisition boundary."""

from face_attendance.capture.camera import (
    CAMERA_BACKENDS,
    CaptureError,
    Frame,
    FrameSource,
    OpenCvCamera,
)

__all__ = ["CAMERA_BACKENDS", "CaptureError", "Frame", "FrameSource", "OpenCvCamera"]
