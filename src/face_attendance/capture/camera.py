"""Camera frame acquisition with explicit failure handling.

Raw frames stay in memory only; nothing in this module writes image data
to disk.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from types import TracebackType
from typing import Callable, Protocol

import numpy as np

from face_attendance.contracts import FrameMetadata


class CaptureError(RuntimeError):
    """Raised when a camera cannot be opened, read, or produces bad frames."""


@dataclass
class Frame:
    """A raw in-memory camera frame paired with validated metadata."""

    image: np.ndarray
    metadata: FrameMetadata


class FrameSource(Protocol):
    """Anything that can produce frames for the recognition pipeline."""

    def open(self) -> None: ...

    def read(self) -> Frame: ...

    def close(self) -> None: ...


class OpenCvCamera:
    """FrameSource backed by cv2.VideoCapture.

    The capture factory is injectable so error paths are unit-testable
    without real hardware.
    """

    def __init__(
        self,
        camera_index: int = 0,
        camera_id: str | None = None,
        capture_factory: Callable[[int], object] | None = None,
    ) -> None:
        if camera_index < 0:
            raise ValueError("camera_index must be >= 0")
        self._camera_index = camera_index
        self._camera_id = camera_id or f"camera-{camera_index}"
        self._capture_factory = capture_factory or _default_capture_factory
        self._capture: object | None = None
        self._frame_counter = 0

    @property
    def camera_id(self) -> str:
        return self._camera_id

    def open(self) -> None:
        if self._capture is not None:
            return
        try:
            capture = self._capture_factory(self._camera_index)
        except Exception as exc:
            raise CaptureError(
                f"failed to create capture for camera index {self._camera_index}"
            ) from exc
        if not _call_capture(capture, "isOpened"):
            _call_capture(capture, "release")
            raise CaptureError(
                f"camera index {self._camera_index} could not be opened; "
                "check that the device exists and is not in use"
            )
        self._capture = capture

    def read(self) -> Frame:
        if self._capture is None:
            raise CaptureError("camera is not open; call open() before read()")

        success, image = _call_capture(self._capture, "read")
        if not success or image is None:
            raise CaptureError(
                f"camera {self._camera_id} failed to deliver a frame; "
                "the device may have been disconnected"
            )
        if not isinstance(image, np.ndarray) or image.size == 0 or image.ndim != 3:
            raise CaptureError(f"camera {self._camera_id} returned a corrupted frame")

        height, width = image.shape[:2]
        metadata = FrameMetadata(
            frame_id=self._frame_counter,
            camera_id=self._camera_id,
            captured_at=datetime.now(timezone.utc),
            width=width,
            height=height,
        )
        self._frame_counter += 1
        return Frame(image=image, metadata=metadata)

    def close(self) -> None:
        if self._capture is None:
            return
        try:
            _call_capture(self._capture, "release")
        finally:
            self._capture = None

    def __enter__(self) -> OpenCvCamera:
        self.open()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()


def _default_capture_factory(camera_index: int) -> object:
    import cv2

    return cv2.VideoCapture(camera_index)


def _call_capture(capture: object, method_name: str) -> object:
    """Call a VideoCapture method defensively so driver errors surface clearly."""

    method = getattr(capture, method_name, None)
    if method is None:
        raise CaptureError(f"capture object does not support {method_name}()")
    try:
        return method()
    except CaptureError:
        raise
    except Exception as exc:
        raise CaptureError(f"capture {method_name}() failed") from exc
