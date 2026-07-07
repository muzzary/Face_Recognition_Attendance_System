import unittest
from pathlib import Path

import numpy as np

from face_attendance.capture import Frame
from face_attendance.contracts import BoundingBox, DetectedFace
from face_attendance.detection import DetectionError, YuNetDetector
from face_attendance.detection.yunet import _row_to_detected_face
from fakes import make_frame

MODELS_DIR = Path(__file__).resolve().parent.parent / "models"
YUNET_PATH = MODELS_DIR / "face_detection_yunet_2023mar.onnx"


def make_yunet_row(
    x: float = 10.0,
    y: float = 12.0,
    width: float = 30.0,
    height: float = 34.0,
    score: float = 0.93,
) -> np.ndarray:
    landmarks = [x + 5, y + 8, x + 20, y + 8, x + 12, y + 16, x + 8, y + 25, x + 18, y + 25]
    return np.array([x, y, width, height, *landmarks, score], dtype=np.float64)


class YuNetRowConversionTests(unittest.TestCase):
    def test_row_converts_to_contract_with_landmarks(self) -> None:
        frame = make_frame(width=64, height=48)

        face = _row_to_detected_face(make_yunet_row(), frame, 64, 48)

        self.assertIsInstance(face, DetectedFace)
        assert face is not None
        self.assertEqual(face.bounding_box, BoundingBox(x=10, y=12, width=30, height=34))
        self.assertAlmostEqual(face.detection_confidence, 0.93)
        assert face.landmarks is not None
        self.assertAlmostEqual(face.landmarks.right_eye.x, 15.0)
        self.assertAlmostEqual(face.landmarks.mouth_left.y, 37.0)

    def test_negative_coordinates_are_clamped(self) -> None:
        frame = make_frame(width=64, height=48)
        row = make_yunet_row(x=-4.0, y=-2.0, width=30.0, height=30.0)

        face = _row_to_detected_face(row, frame, 64, 48)

        assert face is not None
        self.assertEqual(face.bounding_box.x, 0)
        self.assertEqual(face.bounding_box.y, 0)

    def test_box_larger_than_frame_is_clamped(self) -> None:
        frame = make_frame(width=64, height=48)
        row = make_yunet_row(x=50.0, y=40.0, width=100.0, height=100.0)

        face = _row_to_detected_face(row, frame, 64, 48)

        assert face is not None
        self.assertLessEqual(face.bounding_box.x + face.bounding_box.width, 64)
        self.assertLessEqual(face.bounding_box.y + face.bounding_box.height, 48)

    def test_degenerate_box_is_dropped(self) -> None:
        frame = make_frame(width=64, height=48)
        row = make_yunet_row(x=64.0, y=10.0, width=20.0, height=20.0)

        self.assertIsNone(_row_to_detected_face(row, frame, 64, 48))

    def test_short_row_raises(self) -> None:
        frame = make_frame(width=64, height=48)

        with self.assertRaises(DetectionError):
            _row_to_detected_face(np.zeros(5), frame, 64, 48)

    def test_out_of_range_score_is_clamped(self) -> None:
        frame = make_frame(width=64, height=48)
        row = make_yunet_row(score=1.7)

        face = _row_to_detected_face(row, frame, 64, 48)

        assert face is not None
        self.assertEqual(face.detection_confidence, 1.0)


class YuNetDetectorTests(unittest.TestCase):
    def test_missing_model_file_raises_clear_error(self) -> None:
        detector = YuNetDetector(model_path="does/not/exist.onnx")

        with self.assertRaises(DetectionError) as ctx:
            detector.detect(make_frame())
        self.assertIn("download_models", str(ctx.exception))

    def test_invalid_frame_image_raises(self) -> None:
        detector = YuNetDetector(model_path="does/not/exist.onnx")
        frame = make_frame()
        frame.image = np.zeros((0, 0, 3), dtype=np.uint8)

        with self.assertRaises(DetectionError):
            detector.detect(frame)

    def test_invalid_score_threshold_rejected(self) -> None:
        with self.assertRaises(ValueError):
            YuNetDetector(model_path="x.onnx", score_threshold=0.0)

    @unittest.skipUnless(YUNET_PATH.is_file(), "YuNet model not downloaded")
    def test_real_model_returns_empty_list_for_blank_frame(self) -> None:
        detector = YuNetDetector(model_path=YUNET_PATH)
        frame = make_frame(width=320, height=240)

        self.assertEqual(detector.detect(frame), [])


if __name__ == "__main__":
    unittest.main()
