import unittest

import numpy as np

from face_attendance.contracts import (
    BoundingBox,
    DetectedFace,
    FaceLandmarks,
    LivenessStatus,
    Point,
)
from face_attendance.liveness import LivenessError, MicroMovementLivenessChecker
from fakes import make_frame

# Base face geometry: inter-ocular distance 60px.
BASE_POINTS = np.array(
    [
        [160.0, 100.0],  # right eye
        [100.0, 100.0],  # left eye
        [130.0, 130.0],  # nose tip
        [150.0, 155.0],  # mouth right
        [110.0, 155.0],  # mouth left
    ]
)


def face_from_points(
    points: np.ndarray, frame_id: int, captured_at=None
) -> DetectedFace:
    frame = make_frame(
        frame_id=frame_id, width=320, height=240, captured_at=captured_at
    )
    labels = ("right_eye", "left_eye", "nose_tip", "mouth_right", "mouth_left")
    landmarks = FaceLandmarks(
        **{
            label: Point(x=float(point[0]), y=float(point[1]))
            for label, point in zip(labels, points)
        }
    )
    return DetectedFace(
        frame=frame.metadata,
        bounding_box=BoundingBox(x=80, y=80, width=100, height=100),
        detection_confidence=0.95,
        landmarks=landmarks,
    )


def run_sequence(
    checker: MicroMovementLivenessChecker,
    point_sets: list[np.ndarray],
    track_id: str = "EMP-001",
    start_frame: int = 0,
):
    result = None
    for offset, points in enumerate(point_sets):
        result = checker.observe(track_id, face_from_points(points, start_frame + offset))
    assert result is not None
    return result


def static_sequence(count: int) -> list[np.ndarray]:
    return [BASE_POINTS.copy() for _ in range(count)]


def waved_photo_sequence(count: int) -> list[np.ndarray]:
    """Rigid translation + slight rotation: a photo moved by hand."""

    sequences = []
    for index in range(count):
        angle = 0.02 * np.sin(index)
        rotation = np.array(
            [[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]]
        )
        centroid = BASE_POINTS.mean(axis=0)
        rotated = (BASE_POINTS - centroid) @ rotation.T + centroid
        sequences.append(rotated + np.array([2.0 * index, 1.0 * index]))
    return sequences


def live_sequence(count: int, seed: int = 7) -> list[np.ndarray]:
    """Head drift plus independent per-landmark jitter: a live face."""

    rng = np.random.default_rng(seed)
    sequences = []
    position = np.zeros(2)
    for _ in range(count):
        position = position + rng.normal(0.0, 1.2, size=2)
        jitter = rng.normal(0.0, 0.9, size=BASE_POINTS.shape)
        sequences.append(BASE_POINTS + position + jitter)
    return sequences


class LivenessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.checker = MicroMovementLivenessChecker(window_size=12)

    def test_window_not_full_is_unknown(self) -> None:
        result = run_sequence(self.checker, live_sequence(5))

        self.assertEqual(result.status, LivenessStatus.UNKNOWN)
        self.assertEqual(result.frame_count, 5)

    def test_live_face_passes(self) -> None:
        result = run_sequence(self.checker, live_sequence(12))

        self.assertEqual(result.status, LivenessStatus.PASSED)
        self.assertGreaterEqual(result.confidence_score, 0.5)

    def test_static_photo_fails(self) -> None:
        result = run_sequence(self.checker, static_sequence(12))

        self.assertEqual(result.status, LivenessStatus.FAILED)
        assert result.reason is not None
        self.assertIn("static photo", result.reason)

    def test_waved_photo_fails_as_rigid(self) -> None:
        result = run_sequence(self.checker, waved_photo_sequence(12))

        self.assertEqual(result.status, LivenessStatus.FAILED)
        assert result.reason is not None
        self.assertIn("rigid", result.reason)

    def test_track_gap_resets_evidence(self) -> None:
        from datetime import datetime, timedelta, timezone

        start = datetime(2026, 7, 7, 9, 0, tzinfo=timezone.utc)
        frames = live_sequence(8)
        for offset, points in enumerate(frames):
            self.checker.observe(
                "EMP-001",
                face_from_points(
                    points, offset, captured_at=start + timedelta(milliseconds=33 * offset)
                ),
            )

        # Person disappears for 10 seconds, then returns.
        result = self.checker.observe(
            "EMP-001",
            face_from_points(BASE_POINTS, 108, captured_at=start + timedelta(seconds=10)),
        )

        self.assertEqual(result.status, LivenessStatus.UNKNOWN)
        self.assertEqual(result.frame_count, 1)

    def test_dropped_frames_do_not_reset_evidence(self) -> None:
        # Under load the pipeline processes e.g. every 16th camera frame;
        # wall-clock gaps stay small, so evidence must keep accumulating.
        from datetime import datetime, timedelta, timezone

        start = datetime(2026, 7, 7, 9, 0, tzinfo=timezone.utc)
        result = None
        for index, points in enumerate(live_sequence(12)):
            result = self.checker.observe(
                "EMP-001",
                face_from_points(
                    points,
                    frame_id=index * 16,  # large frame-id jumps
                    captured_at=start + timedelta(milliseconds=500 * index),
                ),
            )

        assert result is not None
        self.assertEqual(result.status, LivenessStatus.PASSED)

    def test_tracks_are_independent(self) -> None:
        run_sequence(self.checker, live_sequence(12), track_id="EMP-001")

        result = self.checker.observe(
            "EMP-002", face_from_points(BASE_POINTS, frame_id=50)
        )

        self.assertEqual(result.status, LivenessStatus.UNKNOWN)
        self.assertEqual(result.frame_count, 1)

    def test_reset_clears_track(self) -> None:
        run_sequence(self.checker, live_sequence(12))
        self.checker.reset("EMP-001")

        result = self.checker.observe(
            "EMP-001", face_from_points(BASE_POINTS, frame_id=12)
        )

        self.assertEqual(result.frame_count, 1)

    def test_missing_landmarks_raise(self) -> None:
        frame = make_frame(width=320, height=240)
        face = DetectedFace(
            frame=frame.metadata,
            bounding_box=BoundingBox(x=10, y=10, width=50, height=50),
            detection_confidence=0.9,
        )

        with self.assertRaises(LivenessError):
            self.checker.observe("EMP-001", face)

    def test_small_window_rejected(self) -> None:
        with self.assertRaises(ValueError):
            MicroMovementLivenessChecker(window_size=2)


if __name__ == "__main__":
    unittest.main()
