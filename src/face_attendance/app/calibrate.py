"""Camera-specific liveness calibration.

Every camera has a different landmark-detection noise floor and a different
achievable processing frame rate, both of which directly affect the raw
motion and deformation values liveness computes (see README "Liveness"
section - these values are NOT universal constants, they were tuned from one
specific camera). Run this once per new terminal/camera before trusting the
shipped FA_LIVENESS_* defaults.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

from face_attendance.capture import FrameSource
from face_attendance.contracts import LivenessStatus
from face_attendance.detection.base import FaceDetector
from face_attendance.liveness import MicroMovementLivenessChecker

MIN_USEFUL_SAMPLES = 5
_TRACK_ID = "calibration"


@dataclass
class CalibrationResult:
    """Raw (motion, deformation) samples collected during natural movement."""

    samples: list[tuple[float, float]] = field(default_factory=list)

    @property
    def sample_count(self) -> int:
        return len(self.samples)

    @property
    def motion_range(self) -> tuple[float, float] | None:
        if not self.samples:
            return None
        values = [motion for motion, _ in self.samples]
        return min(values), max(values)

    @property
    def deformation_range(self) -> tuple[float, float] | None:
        if not self.samples:
            return None
        values = [deformation for _, deformation in self.samples]
        return min(values), max(values)

    def recommended_max_motion(self, margin: float = 1.3, floor: float = 0.05) -> float:
        """Observed peak natural motion, plus a safety margin."""

        motion_range = self.motion_range
        if motion_range is None:
            return floor
        return max(floor, motion_range[1] * margin)

    def recommended_min_deformation(
        self, default: float = 0.003, margin: float = 0.5
    ) -> float:
        """Comfortably below the smallest deformation observed, never above
        the shipped default (only tighten, never loosen, without evidence)."""

        deformation_range = self.deformation_range
        if deformation_range is None:
            return default
        return min(default, deformation_range[0] * margin)


def run_liveness_calibration(
    detector: FaceDetector,
    frame_source: FrameSource,
    duration_seconds: float = 20.0,
    window_size: int = 16,
    on_message: Callable[[str], None] = print,
    clock: Callable[[], float] = time.monotonic,
) -> CalibrationResult:
    """Collect motion/deformation samples from natural movement.

    Uses a checker with no gating thresholds so every full window is
    recorded - this reuses the exact same motion/deformation computation the
    real liveness gate uses, just without pass/fail applied. `clock` is
    injectable so tests can drive this deterministically instead of racing
    real wall-clock time against a fake frame source.
    """

    checker = MicroMovementLivenessChecker(
        window_size=window_size,
        min_motion=0.0,
        max_motion=1_000_000.0,
        min_deformation=0.0,
    )
    result = CalibrationResult()

    on_message(
        f"Calibrating for {duration_seconds:.0f}s - move naturally: turn your "
        "head, glance around, nod, as if arriving at work. Do not hold up a "
        "photo or screen; this session should reflect normal live behavior."
    )

    start = clock()
    while clock() - start < duration_seconds:
        frame = frame_source.read()
        faces = detector.detect(frame)
        if len(faces) != 1 or faces[0].landmarks is None:
            continue
        liveness = checker.observe(_TRACK_ID, faces[0])
        if liveness.status is not LivenessStatus.UNKNOWN:
            assert liveness.motion is not None and liveness.deformation is not None
            result.samples.append((liveness.motion, liveness.deformation))

    return result


def print_calibration_report(
    result: CalibrationResult,
    current_max_motion: float,
    current_min_deformation: float,
    on_message: Callable[[str], None] = print,
) -> None:
    """Print observed ranges and recommendations, comparing against the
    currently configured values so a tightened recommendation is flagged
    rather than silently trusted.

    A single short session can easily under-sample the true range of
    natural movement. If the currently configured values were already
    validated (e.g. across multiple real sessions), a *narrower* value
    recommended from one shorter run is a regression risk, not an
    improvement - this was caught directly during this project's own
    development (see docs/phase-log.md).
    """

    if result.sample_count < MIN_USEFUL_SAMPLES:
        on_message(
            f"warning: only {result.sample_count} full evaluation window(s) captured; "
            "move more, or run with --duration higher, for a reliable recommendation."
        )
        if result.sample_count == 0:
            return

    motion_range = result.motion_range
    deformation_range = result.deformation_range
    assert motion_range is not None and deformation_range is not None

    on_message(f"\n{result.sample_count} evaluation windows captured.")
    on_message(f"  motion observed range:      {motion_range[0]:.4f} - {motion_range[1]:.4f}")
    on_message(
        f"  deformation observed range: {deformation_range[0]:.4f} - {deformation_range[1]:.4f}"
    )

    recommended_max_motion = result.recommended_max_motion()
    recommended_min_deformation = result.recommended_min_deformation()

    on_message("\nRecommended settings for this camera:")
    on_message(
        f"  FA_LIVENESS_MAX_MOTION={recommended_max_motion:.4f}  "
        f"(currently configured: {current_max_motion:.4f})"
    )
    if recommended_max_motion < current_max_motion:
        on_message(
            "  NOTE: this is TIGHTER than the currently configured value. A "
            "single short session can under-sample natural movement variety "
            "- do not adopt a narrower ceiling than an already-validated one "
            "without more evidence (a longer --duration, multiple runs on "
            "different days, or several real users). Doing so risks "
            "reintroducing false rejects for legitimate but slightly more "
            "energetic natural movement."
        )
    on_message(
        f"  FA_LIVENESS_MIN_DEFORMATION={recommended_min_deformation:.4f}  "
        f"(currently configured: {current_min_deformation:.4f})"
    )
    if recommended_min_deformation < current_min_deformation:
        on_message(
            "  NOTE: this is LOWER than the currently configured floor, which "
            "makes the spoof-rejection check MORE permissive (a rigid object "
            "needs to deform even less to still be flagged). Only lower this "
            "if you have specific evidence the current floor false-rejects "
            "genuine live users on this camera."
        )
    on_message(
        "\nIf you adopt either value, set it as an environment variable "
        "before running 'attend' or 'enroll' on this machine, then "
        "re-verify with the demo checklist (docs/demo-checklist.md) - both "
        "a live-face pass and a spoof rejection should still hold."
    )
