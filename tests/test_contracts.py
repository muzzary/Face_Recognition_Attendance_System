from datetime import datetime, timezone
import math
import unittest

from pydantic import ValidationError

from face_attendance.contracts import (
    AttendanceEvent,
    AttendanceEventType,
    BoundingBox,
    DetectedFace,
    EmployeeRecord,
    FaceEmbedding,
    FrameMetadata,
    LivenessResult,
    LivenessStatus,
    MatchResult,
)


NOW = datetime(2026, 7, 6, 12, 0, tzinfo=timezone.utc)


class ContractTests(unittest.TestCase):
    def test_valid_pipeline_contracts_are_accepted(self) -> None:
        frame = FrameMetadata(
            frame_id=1,
            camera_id="front-door",
            captured_at=NOW,
            width=1280,
            height=720,
        )
        face = DetectedFace(
            frame=frame,
            bounding_box=BoundingBox(x=10, y=20, width=120, height=140),
            detection_confidence=0.94,
        )
        embedding = FaceEmbedding(
            vector=[0.1, 0.2, 0.3],
            dimensions=3,
            model_name="demo-model",
        )
        employee = EmployeeRecord(
            employee_id="EMP-001",
            full_name="Test Employee",
            created_at=NOW,
        )
        match = MatchResult(
            is_match=True,
            employee_id=employee.employee_id,
            distance=0.32,
            threshold=0.45,
            confidence_score=0.88,
        )
        liveness = LivenessResult(
            status=LivenessStatus.PASSED,
            method="blink",
            frame_count=12,
            confidence_score=0.8,
        )
        event = AttendanceEvent(
            employee_id=employee.employee_id,
            occurred_at=NOW,
            event_type=AttendanceEventType.CLOCK_IN,
            confidence_score=match.confidence_score,
            match_distance=match.distance,
        )

        self.assertEqual(face.frame.camera_id, "front-door")
        self.assertEqual(embedding.dimensions, 3)
        self.assertEqual(liveness.status, LivenessStatus.PASSED)
        self.assertIsNone(liveness.motion)
        self.assertIsNone(liveness.deformation)
        self.assertEqual(event.event_type, AttendanceEventType.CLOCK_IN)

    def test_liveness_result_accepts_raw_metrics(self) -> None:
        liveness = LivenessResult(
            status=LivenessStatus.FAILED,
            method="micro-movement-v1",
            frame_count=12,
            confidence_score=0.1,
            reason="possible static photo",
            motion=0.0012,
            deformation=0.0031,
        )

        self.assertEqual(liveness.motion, 0.0012)
        self.assertEqual(liveness.deformation, 0.0031)

    def test_liveness_result_rejects_negative_metrics(self) -> None:
        with self.assertRaises(ValidationError):
            LivenessResult(
                status=LivenessStatus.PASSED,
                method="micro-movement-v1",
                frame_count=12,
                confidence_score=0.8,
                motion=-0.001,
            )

    def test_extra_fields_are_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            FrameMetadata(
                frame_id=1,
                camera_id="front-door",
                captured_at=NOW,
                width=1280,
                height=720,
                raw_image_path="data/frame.jpg",
            )

    def test_naive_timestamps_are_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            AttendanceEvent(
                employee_id="EMP-001",
                occurred_at=datetime(2026, 7, 6, 12, 0),
                event_type=AttendanceEventType.CLOCK_IN,
                confidence_score=0.9,
                match_distance=0.2,
            )

    def test_embedding_dimension_must_match_vector_length(self) -> None:
        with self.assertRaises(ValidationError):
            FaceEmbedding(
                vector=[0.1, 0.2],
                dimensions=3,
                model_name="demo-model",
            )

    def test_embedding_values_must_be_finite(self) -> None:
        with self.assertRaises(ValidationError):
            FaceEmbedding(
                vector=[0.1, math.inf],
                dimensions=2,
                model_name="demo-model",
            )

    def test_match_requires_employee_id_only_for_matches(self) -> None:
        with self.assertRaises(ValidationError):
            MatchResult(
                is_match=True,
                distance=0.2,
                threshold=0.45,
                confidence_score=0.91,
            )

        with self.assertRaises(ValidationError):
            MatchResult(
                is_match=False,
                employee_id="EMP-001",
                distance=0.7,
                threshold=0.45,
                confidence_score=0.1,
            )

    def test_failed_liveness_requires_reason(self) -> None:
        with self.assertRaises(ValidationError):
            LivenessResult(
                status=LivenessStatus.FAILED,
                method="micro-movement",
                frame_count=8,
                confidence_score=0.2,
            )


if __name__ == "__main__":
    unittest.main()
