import unittest

from face_attendance.app.attend import AttendStats, _liveness_metrics_suffix, _report_output
from face_attendance.attendance_logging import AttendanceDecision
from face_attendance.contracts import (
    AttendanceEvent,
    AttendanceEventType,
    LivenessResult,
    LivenessStatus,
    MatchResult,
)
from face_attendance.pipeline import FaceOutcome, RecognitionOutput
from fakes import make_detected_face, make_frame

NOW = "2026-07-08T09:00:00+00:00"


def liveness_failed(reason: str, motion: float, deformation: float | None = None) -> LivenessResult:
    return LivenessResult(
        status=LivenessStatus.FAILED,
        method="micro-movement-v1",
        frame_count=12,
        confidence_score=0.1,
        reason=reason,
        motion=motion,
        deformation=deformation,
    )


class LivenessMetricsSuffixTests(unittest.TestCase):
    def test_none_liveness_gives_empty_suffix(self) -> None:
        self.assertEqual(_liveness_metrics_suffix(None), "")

    def test_gathering_evidence_has_no_metrics_yet(self) -> None:
        result = LivenessResult(
            status=LivenessStatus.UNKNOWN,
            method="micro-movement-v1",
            frame_count=3,
            confidence_score=0.0,
            reason="gathering evidence (3/12 frames)",
        )
        self.assertEqual(_liveness_metrics_suffix(result), "")

    def test_static_photo_failure_shows_motion_only(self) -> None:
        result = liveness_failed("possible static photo", motion=0.0012)
        self.assertEqual(_liveness_metrics_suffix(result), " [motion=0.0012]")

    def test_rigid_failure_shows_both_metrics(self) -> None:
        result = liveness_failed("possible rigid spoof", motion=0.0091, deformation=0.0021)
        self.assertEqual(
            _liveness_metrics_suffix(result), " [motion=0.0091, deform=0.0021]"
        )


class ReportOutputDedupeTests(unittest.TestCase):
    def make_outcome(self, liveness: LivenessResult, employee_id: str = "EMP-001") -> RecognitionOutput:
        frame = make_frame()
        face = make_detected_face(frame)
        match = MatchResult(
            is_match=True,
            employee_id=employee_id,
            distance=0.2,
            threshold=0.637,
            confidence_score=0.8,
        )
        decision = AttendanceDecision(
            logged=False, event=None, reason=f"liveness not passed: {liveness.reason}"
        )
        outcome = FaceOutcome(face=face, match=match, liveness=liveness, decision=decision)
        return RecognitionOutput(frame=frame.metadata, outcomes=[outcome])

    def test_metrics_print_once_per_reason_change_not_every_frame(self) -> None:
        stats = AttendStats()
        last_messages: dict[str, str] = {}
        messages: list[str] = []

        # Same failure category repeated 3x with slightly different (noisy)
        # motion readings - must dedupe to a single printed line.
        for motion in (0.0011, 0.0014, 0.0009):
            output = self.make_outcome(liveness_failed("possible static photo", motion=motion))
            _report_output(output, stats, last_messages, messages.append)

        self.assertEqual(len(messages), 1)
        self.assertIn("motion=0.0011", messages[0])

    def test_reason_change_prints_new_metrics(self) -> None:
        stats = AttendStats()
        last_messages: dict[str, str] = {}
        messages: list[str] = []

        _report_output(
            self.make_outcome(liveness_failed("possible static photo", motion=0.001)),
            stats,
            last_messages,
            messages.append,
        )
        _report_output(
            self.make_outcome(
                liveness_failed("possible rigid spoof", motion=0.009, deformation=0.002)
            ),
            stats,
            last_messages,
            messages.append,
        )

        self.assertEqual(len(messages), 2)
        self.assertIn("motion=0.0010", messages[0])
        self.assertIn("deform=0.0020", messages[1])

    def test_clock_in_message_includes_passing_metrics(self) -> None:
        stats = AttendStats()
        frame = make_frame()
        face = make_detected_face(frame)
        match = MatchResult(
            is_match=True,
            employee_id="EMP-001",
            distance=0.1,
            threshold=0.637,
            confidence_score=0.9,
        )
        liveness = LivenessResult(
            status=LivenessStatus.PASSED,
            method="micro-movement-v1",
            frame_count=12,
            confidence_score=0.9,
            motion=0.015,
            deformation=0.02,
        )
        event = AttendanceEvent(
            employee_id="EMP-001",
            occurred_at=NOW,
            event_type=AttendanceEventType.CLOCK_IN,
            confidence_score=0.9,
            match_distance=0.1,
        )
        decision = AttendanceDecision(logged=True, event=event, reason="logged clock_in")
        outcome = FaceOutcome(face=face, match=match, liveness=liveness, decision=decision)
        output = RecognitionOutput(frame=frame.metadata, outcomes=[outcome])
        messages: list[str] = []

        _report_output(output, stats, {}, messages.append)

        self.assertEqual(stats.events_logged, 1)
        self.assertIn("motion=0.0150, deform=0.0200", messages[0])


if __name__ == "__main__":
    unittest.main()
