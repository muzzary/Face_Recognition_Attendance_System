import unittest

import numpy as np

from face_attendance.app import (
    CalibrationResult,
    print_calibration_report,
    run_liveness_calibration,
)
from face_attendance.contracts import FaceLandmarks, Point
from fakes import FakeFrameSource, make_detected_face, make_frame


class VaryingLandmarkDetector:
    """Returns one face per frame with landmarks that genuinely move a bit
    each call, so motion/deformation come out non-zero (unlike a fixed
    repeating detector)."""

    def __init__(self) -> None:
        self._counter = 0

    def detect(self, frame):
        self._counter += 1
        offset = 0.6 * (self._counter % 5)
        labels = ("right_eye", "left_eye", "nose_tip", "mouth_right", "mouth_left")
        base = {
            "right_eye": (160.0, 100.0),
            "left_eye": (100.0, 100.0),
            "nose_tip": (130.0, 130.0),
            "mouth_right": (150.0, 155.0),
            "mouth_left": (110.0, 155.0),
        }
        landmarks = FaceLandmarks(
            **{
                label: Point(x=base[label][0] + offset, y=base[label][1] - offset)
                for label in labels
            }
        )
        return [make_detected_face(frame, landmarks=landmarks)]


def make_fake_clock(increment: float = 1.0):
    state = {"t": 0.0}

    def clock() -> float:
        value = state["t"]
        state["t"] += increment
        return value

    return clock


class CalibrationResultTests(unittest.TestCase):
    def test_recommended_max_motion_applies_margin(self) -> None:
        result = CalibrationResult(samples=[(0.05, 0.01), (0.09, 0.02), (0.03, 0.015)])

        self.assertAlmostEqual(result.recommended_max_motion(margin=1.3), 0.09 * 1.3)

    def test_recommended_max_motion_respects_floor_when_empty(self) -> None:
        result = CalibrationResult()

        self.assertEqual(result.recommended_max_motion(floor=0.05), 0.05)

    def test_recommended_min_deformation_never_exceeds_default(self) -> None:
        # Observed floor is high (0.05) - recommendation must stay <= default,
        # never loosen safety without direct evidence it's needed.
        result = CalibrationResult(samples=[(0.05, 0.05), (0.06, 0.06)])

        self.assertLessEqual(result.recommended_min_deformation(default=0.003), 0.003)

    def test_recommended_min_deformation_tightens_when_camera_is_quieter(self) -> None:
        result = CalibrationResult(samples=[(0.05, 0.0004), (0.06, 0.0006)])

        recommended = result.recommended_min_deformation(default=0.003, margin=0.5)

        self.assertAlmostEqual(recommended, 0.0004 * 0.5)


class RunLivenessCalibrationTests(unittest.TestCase):
    def test_collects_samples_across_the_session(self) -> None:
        frames = [make_frame(frame_id=i) for i in range(50)]
        source = FakeFrameSource(frames)
        source.open()
        clock = make_fake_clock(increment=1.0)

        result = run_liveness_calibration(
            VaryingLandmarkDetector(),
            source,
            duration_seconds=16.0,
            window_size=5,
            on_message=lambda _: None,
            clock=clock,
        )

        self.assertGreater(result.sample_count, 0)
        for motion, deformation in result.samples:
            self.assertGreaterEqual(motion, 0.0)
            self.assertGreaterEqual(deformation, 0.0)

    def test_frames_with_no_face_are_skipped_not_fatal(self) -> None:
        class SometimesNoFaceDetector(VaryingLandmarkDetector):
            def detect(self, frame):
                if frame.metadata.frame_id % 3 == 0:
                    return []
                return super().detect(frame)

        frames = [make_frame(frame_id=i) for i in range(50)]
        source = FakeFrameSource(frames)
        source.open()
        clock = make_fake_clock(increment=1.0)

        result = run_liveness_calibration(
            SometimesNoFaceDetector(),
            source,
            duration_seconds=16.0,
            window_size=5,
            on_message=lambda _: None,
            clock=clock,
        )

        self.assertGreaterEqual(result.sample_count, 0)


class PrintCalibrationReportTests(unittest.TestCase):
    def test_warns_on_too_few_samples(self) -> None:
        result = CalibrationResult(samples=[(0.05, 0.01)])
        messages: list[str] = []

        print_calibration_report(result, on_message=messages.append)

        self.assertTrue(any("only 1" in m for m in messages))

    def test_empty_result_warns_and_stops(self) -> None:
        result = CalibrationResult()
        messages: list[str] = []

        print_calibration_report(result, on_message=messages.append)

        self.assertTrue(any("0 full evaluation" in m for m in messages))
        self.assertFalse(any("Recommended settings" in m for m in messages))

    def test_prints_recommendations_for_enough_samples(self) -> None:
        result = CalibrationResult(
            samples=[(0.02 + 0.001 * i, 0.01 + 0.0005 * i) for i in range(10)]
        )
        messages: list[str] = []

        print_calibration_report(result, on_message=messages.append)

        joined = "\n".join(messages)
        self.assertIn("FA_LIVENESS_MAX_MOTION", joined)
        self.assertIn("FA_LIVENESS_MIN_DEFORMATION", joined)


if __name__ == "__main__":
    unittest.main()
