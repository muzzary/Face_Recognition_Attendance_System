"""Reusable fakes for pipeline tests. No real hardware or models required."""

from __future__ import annotations

from datetime import datetime, timezone

import numpy as np

from face_attendance.capture import CaptureError, Frame
from face_attendance.contracts import FrameMetadata


class FakeVideoCapture:
    """Stands in for cv2.VideoCapture in unit tests."""

    def __init__(
        self,
        opened: bool = True,
        frames: list[np.ndarray | None] | None = None,
        read_raises: bool = False,
    ) -> None:
        self._opened = opened
        self._frames = list(frames) if frames is not None else []
        self._read_raises = read_raises
        self.released = False

    def isOpened(self) -> bool:  # noqa: N802 - mirrors cv2 API
        return self._opened

    def read(self) -> tuple[bool, np.ndarray | None]:
        if self._read_raises:
            raise RuntimeError("simulated driver failure")
        if not self._frames:
            return False, None
        frame = self._frames.pop(0)
        if frame is None:
            return False, None
        return True, frame

    def release(self) -> None:
        self.released = True


def make_image(width: int = 64, height: int = 48, value: int = 128) -> np.ndarray:
    return np.full((height, width, 3), value, dtype=np.uint8)


def make_frame(
    frame_id: int = 0,
    width: int = 64,
    height: int = 48,
    camera_id: str = "camera-test",
    image: np.ndarray | None = None,
) -> Frame:
    if image is None:
        image = make_image(width=width, height=height)
    metadata = FrameMetadata(
        frame_id=frame_id,
        camera_id=camera_id,
        captured_at=datetime.now(timezone.utc),
        width=image.shape[1],
        height=image.shape[0],
    )
    return Frame(image=image, metadata=metadata)


class FakeFrameSource:
    """FrameSource that serves a fixed list of frames, then fails explicitly."""

    def __init__(self, frames: list[Frame]) -> None:
        self._frames = list(frames)
        self.opened = False
        self.closed = False

    def open(self) -> None:
        self.opened = True

    def read(self) -> Frame:
        if not self.opened:
            raise CaptureError("fake camera not opened")
        if not self._frames:
            raise CaptureError("fake camera has no more frames")
        return self._frames.pop(0)

    def close(self) -> None:
        self.closed = True
