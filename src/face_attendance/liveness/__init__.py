"""Anti-spoofing liveness boundary."""

from face_attendance.liveness.micro_movement import (
    LIVENESS_METHOD,
    LivenessError,
    MicroMovementLivenessChecker,
)

__all__ = ["LIVENESS_METHOD", "LivenessError", "MicroMovementLivenessChecker"]
