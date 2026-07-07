"""Camera frame acquisition with explicit failure handling.

Raw frames stay in memory only; nothing in this module writes image data
to disk.
"""

from __future__ import annotations

import logging
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from types import TracebackType
from typing import Callable, Protocol

import numpy as np

from face_attendance.contracts import FrameMetadata

logger = logging.getLogger(__name__)

CAMERA_BACKENDS = ("auto", "default", "msmf", "dshow")


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
        backend: str = "auto",
    ) -> None:
        if camera_index < 0:
            raise ValueError("camera_index must be >= 0")
        if backend not in CAMERA_BACKENDS:
            raise ValueError(f"backend must be one of {CAMERA_BACKENDS}")
        self._camera_index = camera_index
        self._camera_id = camera_id or f"camera-{camera_index}"
        self._capture_factory = capture_factory
        self._backend = backend
        self._capture: object | None = None
        self._frame_counter = 0

    @property
    def camera_id(self) -> str:
        return self._camera_id

    def open(self) -> None:
        if self._capture is not None:
            return
        if self._capture_factory is not None:
            # Injected factory (tests, custom rigs): open without probing.
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
            return
        self._capture = _create_verified_capture(self._camera_index, self._backend)

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


def _backend_candidates(backend: str) -> list[tuple[str, int | None]]:
    """Ordered (name, cv2 flag) candidates to try for a backend choice.

    "auto" tries the platform default first and falls back to DirectShow on
    Windows — some webcams open under MSMF but never deliver frames.
    """

    import cv2

    if backend == "auto":
        candidates: list[tuple[str, int | None]] = [("default", None)]
        if sys.platform == "win32":
            candidates.append(("dshow", cv2.CAP_DSHOW))
        return candidates
    if backend == "default":
        return [("default", None)]
    if backend == "msmf":
        return [("msmf", cv2.CAP_MSMF)]
    if backend == "dshow":
        return [("dshow", cv2.CAP_DSHOW)]
    raise ValueError(f"unknown camera backend {backend!r}")


def _probe_delivers_frames(capture: object, attempts: int = 10) -> bool:
    """A capture can report open yet never produce frames; verify it does."""

    for _ in range(attempts):
        try:
            success, image = _call_capture(capture, "read")
        except CaptureError:
            return False
        if success and image is not None:
            return True
        time.sleep(0.05)
    return False


def _create_verified_capture(camera_index: int, backend: str) -> object:
    """Open the camera with the first backend that actually delivers frames."""

    import cv2

    failures: list[str] = []
    for name, flag in _backend_candidates(backend):
        try:
            capture = (
                cv2.VideoCapture(camera_index)
                if flag is None
                else cv2.VideoCapture(camera_index, flag)
            )
        except Exception as exc:  # noqa: BLE001 - driver layer can throw anything
            failures.append(f"{name}: backend failed to initialize ({exc})")
            continue
        if not _call_capture(capture, "isOpened"):
            _call_capture(capture, "release")
            failures.append(f"{name}: could not open the device")
            continue
        if not _probe_delivers_frames(capture):
            _call_capture(capture, "release")
            failures.append(f"{name}: opened but delivered no frames")
            continue
        if failures:
            logger.info(
                "camera %d: using %s backend after fallback (%s)",
                camera_index,
                name,
                "; ".join(failures),
            )
        return capture

    raise CaptureError(
        f"camera index {camera_index} is unusable with every backend tried: "
        + "; ".join(failures)
        + ". Check that the device exists, is not in use, and that Windows "
        "camera privacy settings allow desktop apps."
    )


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
