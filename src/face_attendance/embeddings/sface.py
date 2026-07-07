"""SFace embedding adapter (cv2.FaceRecognizerSF, ONNX model file).

Produces 128-dimensional float vectors. Only numeric embeddings ever leave
this module; aligned face crops are discarded immediately.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from face_attendance.capture import Frame
from face_attendance.contracts import DetectedFace, FaceEmbedding
from face_attendance.embeddings.base import EmbeddingError

SFACE_MODEL_FILENAME = "face_recognition_sface_2021dec.onnx"
SFACE_MODEL_NAME = "sface-2021dec"


class SFaceEmbedder:
    """EmbeddingExtractor backed by cv2.FaceRecognizerSF."""

    def __init__(self, model_path: str | Path) -> None:
        self._model_path = Path(model_path)
        self._recognizer: object | None = None

    @property
    def model_name(self) -> str:
        return SFACE_MODEL_NAME

    def _require_recognizer(self) -> object:
        if self._recognizer is not None:
            return self._recognizer
        if not self._model_path.is_file():
            raise EmbeddingError(
                f"SFace model not found at {self._model_path}; "
                "run scripts/download_models.py first"
            )
        import cv2

        try:
            self._recognizer = cv2.FaceRecognizerSF.create(str(self._model_path), "")
        except cv2.error as exc:
            raise EmbeddingError(
                f"failed to load SFace model from {self._model_path}"
            ) from exc
        return self._recognizer

    def extract(self, frame: Frame, face: DetectedFace) -> FaceEmbedding:
        image = frame.image
        if not isinstance(image, np.ndarray) or image.ndim != 3 or image.size == 0:
            raise EmbeddingError("embedder received an invalid frame image")
        if face.landmarks is None:
            raise EmbeddingError(
                "embedder requires facial landmarks; use a detector that provides them"
            )

        recognizer = self._require_recognizer()
        row = _face_to_yunet_row(face)
        import cv2

        try:
            aligned = recognizer.alignCrop(image, row)
            feature = recognizer.feature(aligned)
        except cv2.error as exc:
            raise EmbeddingError("SFace feature extraction failed") from exc

        vector = np.asarray(feature, dtype=np.float64).flatten()
        if vector.size == 0 or not np.all(np.isfinite(vector)):
            raise EmbeddingError("SFace produced an empty or non-finite embedding")

        return FaceEmbedding(
            vector=[float(value) for value in vector],
            dimensions=int(vector.size),
            model_name=SFACE_MODEL_NAME,
        )


def _face_to_yunet_row(face: DetectedFace) -> np.ndarray:
    """Rebuild the 15-value YuNet row that alignCrop expects from a contract."""

    assert face.landmarks is not None
    box = face.bounding_box
    points = face.landmarks.as_points()
    values = [float(box.x), float(box.y), float(box.width), float(box.height)]
    for point in points:
        values.extend((point.x, point.y))
    values.append(face.detection_confidence)
    return np.array(values, dtype=np.float32)
