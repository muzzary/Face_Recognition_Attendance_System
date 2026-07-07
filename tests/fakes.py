"""Reusable fakes for pipeline tests. No real hardware or models required."""

from __future__ import annotations

from datetime import datetime, timezone

import time

import numpy as np

from face_attendance.capture import CaptureError, Frame
from face_attendance.contracts import (
    BoundingBox,
    DetectedFace,
    FaceEmbedding,
    FaceLandmarks,
    FrameMetadata,
    LivenessResult,
    LivenessStatus,
    Point,
)
from face_attendance.detection.base import DetectionError


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
    captured_at: datetime | None = None,
) -> Frame:
    if image is None:
        image = make_image(width=width, height=height)
    metadata = FrameMetadata(
        frame_id=frame_id,
        camera_id=camera_id,
        captured_at=captured_at if captured_at is not None else datetime.now(timezone.utc),
        width=image.shape[1],
        height=image.shape[0],
    )
    return Frame(image=image, metadata=metadata)


def make_landmarks(x: float = 15.0, y: float = 20.0) -> FaceLandmarks:
    return FaceLandmarks(
        right_eye=Point(x=x, y=y),
        left_eye=Point(x=x + 15.0, y=y),
        nose_tip=Point(x=x + 7.0, y=y + 8.0),
        mouth_right=Point(x=x + 3.0, y=y + 17.0),
        mouth_left=Point(x=x + 13.0, y=y + 17.0),
    )


def make_detected_face(
    frame: Frame | None = None,
    x: int = 10,
    y: int = 12,
    width: int = 100,
    height: int = 100,
    confidence: float = 0.95,
    landmarks: FaceLandmarks | None = None,
) -> DetectedFace:
    if frame is None:
        frame = make_frame(width=320, height=240)
    return DetectedFace(
        frame=frame.metadata,
        bounding_box=BoundingBox(x=x, y=y, width=width, height=height),
        detection_confidence=confidence,
        landmarks=landmarks if landmarks is not None else make_landmarks(),
    )


def make_embedding(
    vector: list[float] | None = None, model_name: str = "fake-model"
) -> FaceEmbedding:
    if vector is None:
        vector = [1.0, 0.0, 0.0, 0.0]
    return FaceEmbedding(vector=vector, dimensions=len(vector), model_name=model_name)


class FakeDetector:
    """FaceDetector returning a scripted list of faces per call."""

    def __init__(self, results: list[list[DetectedFace]]) -> None:
        self._results = list(results)

    def detect(self, frame: Frame) -> list[DetectedFace]:
        if not self._results:
            return []
        return self._results.pop(0)


class FakeEmbedder:
    """EmbeddingExtractor returning scripted embeddings per call."""

    def __init__(self, embeddings: list[FaceEmbedding]) -> None:
        self._embeddings = list(embeddings)

    @property
    def model_name(self) -> str:
        return "fake-model"

    def extract(self, frame: Frame, face: DetectedFace) -> FaceEmbedding:
        if not self._embeddings:
            raise AssertionError("FakeEmbedder ran out of scripted embeddings")
        return self._embeddings.pop(0)


class FakeFrameSource:
    """FrameSource that serves a fixed list of frames, then fails explicitly."""

    def __init__(self, frames: list[Frame], read_delay: float = 0.0) -> None:
        self._frames = list(frames)
        self._read_delay = read_delay
        self.opened = False
        self.closed = False

    def open(self) -> None:
        self.opened = True

    def read(self) -> Frame:
        if not self.opened:
            raise CaptureError("fake camera not opened")
        if not self._frames:
            raise CaptureError("fake camera has no more frames")
        if self._read_delay > 0.0:
            time.sleep(self._read_delay)
        return self._frames.pop(0)

    def close(self) -> None:
        self.closed = True


class ScriptedLiveness:
    """Liveness checker that always returns a fixed status."""

    def __init__(self, status: LivenessStatus = LivenessStatus.PASSED) -> None:
        self._status = status
        self.observed: list[str] = []

    def observe(self, track_id: str, face: DetectedFace) -> LivenessResult:
        self.observed.append(track_id)
        return LivenessResult(
            status=self._status,
            method="scripted",
            frame_count=12,
            confidence_score=0.9,
            reason="scripted failure" if self._status is LivenessStatus.FAILED else None,
        )

    def reset(self, track_id: str) -> None:
        pass


class RepeatingDetector:
    """Returns the same faces for every frame; optionally raises first."""

    def __init__(self, faces: list[DetectedFace], failures: int = 0) -> None:
        self._faces = faces
        self._failures = failures

    def detect(self, frame: Frame) -> list[DetectedFace]:
        if self._failures > 0:
            self._failures -= 1
            raise DetectionError("simulated detector failure")
        return list(self._faces)


class RepeatingEmbedder:
    """Returns the same embedding for every face."""

    def __init__(self, vector: list[float]) -> None:
        self._vector = vector

    @property
    def model_name(self) -> str:
        return "fake-model"

    def extract(self, frame: Frame, face: DetectedFace) -> FaceEmbedding:
        return make_embedding(self._vector)
