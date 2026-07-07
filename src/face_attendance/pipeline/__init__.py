"""Non-blocking recognition pipeline boundary."""

from face_attendance.pipeline.worker import (
    FaceOutcome,
    LatestFrameSlot,
    PipelineError,
    RecognitionOutput,
    RecognitionWorker,
)

__all__ = [
    "FaceOutcome",
    "LatestFrameSlot",
    "PipelineError",
    "RecognitionOutput",
    "RecognitionWorker",
]
