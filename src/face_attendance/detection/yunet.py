"""YuNet face detector adapter (ships with opencv-python, ONNX model file).

Keeps cv2 specifics behind the FaceDetector protocol so the rest of the
pipeline only sees validated DetectedFace contracts.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from face_attendance.capture import Frame
from face_attendance.contracts import BoundingBox, DetectedFace, FaceLandmarks, Point
from face_attendance.detection.base import DetectionError

YUNET_MODEL_FILENAME = "face_detection_yunet_2023mar.onnx"


class YuNetDetector:
    """FaceDetector backed by cv2.FaceDetectorYN."""

    def __init__(
        self,
        model_path: str | Path,
        score_threshold: float = 0.8,
        nms_threshold: float = 0.3,
        top_k: int = 50,
    ) -> None:
        if not 0.0 < score_threshold <= 1.0:
            raise ValueError("score_threshold must be in (0, 1]")
        self._model_path = Path(model_path)
        self._score_threshold = score_threshold
        self._nms_threshold = nms_threshold
        self._top_k = top_k
        self._detector: object | None = None
        self._input_size: tuple[int, int] | None = None

    def _require_detector(self) -> object:
        if self._detector is not None:
            return self._detector
        if not self._model_path.is_file():
            raise DetectionError(
                f"YuNet model not found at {self._model_path}; "
                "run scripts/download_models.py first"
            )
        import cv2

        try:
            self._detector = cv2.FaceDetectorYN.create(
                str(self._model_path),
                "",
                (320, 320),
                self._score_threshold,
                self._nms_threshold,
                self._top_k,
            )
        except cv2.error as exc:
            raise DetectionError(
                f"failed to load YuNet model from {self._model_path}"
            ) from exc
        return self._detector

    def detect(self, frame: Frame) -> list[DetectedFace]:
        image = frame.image
        if not isinstance(image, np.ndarray) or image.ndim != 3 or image.size == 0:
            raise DetectionError("detector received an invalid frame image")

        detector = self._require_detector()
        height, width = image.shape[:2]
        import cv2

        try:
            if self._input_size != (width, height):
                detector.setInputSize((width, height))
                self._input_size = (width, height)
            _, faces = detector.detect(image)
        except cv2.error as exc:
            raise DetectionError("YuNet detection failed on frame") from exc

        if faces is None:
            return []
        return [
            face
            for row in np.asarray(faces, dtype=np.float64)
            if (face := _row_to_detected_face(row, frame, width, height)) is not None
        ]


def _row_to_detected_face(
    row: np.ndarray, frame: Frame, frame_width: int, frame_height: int
) -> DetectedFace | None:
    """Convert one YuNet output row to a validated contract.

    Row layout: x, y, w, h, then five (x, y) landmarks, then score.
    Boxes are clamped to the frame; degenerate boxes are dropped.
    """

    if row.shape[0] < 15:
        raise DetectionError(f"unexpected YuNet output row of length {row.shape[0]}")

    # Clamp by shrinking, not shifting: a box hanging off the left/top edge
    # loses the off-frame part instead of sliding onto the wrong pixels.
    raw_x, raw_y = int(round(row[0])), int(round(row[1]))
    x, y = max(0, raw_x), max(0, raw_y)
    box_width = min(int(round(row[2])) - (x - raw_x), frame_width - x)
    box_height = min(int(round(row[3])) - (y - raw_y), frame_height - y)
    if box_width <= 0 or box_height <= 0:
        return None

    landmark_points = [Point(x=float(row[4 + 2 * i]), y=float(row[5 + 2 * i])) for i in range(5)]
    confidence = float(min(max(row[14], 0.0), 1.0))

    return DetectedFace(
        frame=frame.metadata,
        bounding_box=BoundingBox(x=x, y=y, width=box_width, height=box_height),
        detection_confidence=confidence,
        landmarks=FaceLandmarks(
            right_eye=landmark_points[0],
            left_eye=landmark_points[1],
            nose_tip=landmark_points[2],
            mouth_right=landmark_points[3],
            mouth_left=landmark_points[4],
        ),
    )
