"""Face detection boundary."""

from face_attendance.detection.base import DetectionError, FaceDetector
from face_attendance.detection.yunet import YUNET_MODEL_FILENAME, YuNetDetector

__all__ = ["DetectionError", "FaceDetector", "YUNET_MODEL_FILENAME", "YuNetDetector"]
