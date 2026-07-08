"""Multi-frame liveness via micro-movement and non-rigidity analysis.

Evidence is gathered across a window of frames per tracked identity, and two
signals are checked against expected *bands* (not one-sided floors):

1. Motion presence — live heads are never pixel-still, but they also are not
   constantly trembling. A window whose landmark centroid barely moves is a
   mounted/still photo; a window that moves far more than a calm authenticating
   face naturally does is a hand-held photo (a hand shakes more than a head
   held still for a moment).
2. Non-rigid deformation — after removing translation, scale, and in-plane
   rotation from each frame's landmarks, a rigid spoof leaves near-zero
   residual movement in theory, but a hand-tremor-tilted rigid photo actually
   produces *more* apparent residual than a live face's subtle expression
   changes, because tilt (an out-of-plane rotation) is not corrected by this
   in-plane-only normalization. So this is also a band, not a floor.

Both bands were set from real measured data (see docs/phase-log.md), not
guessed: a live face's natural range sits inside the band, a hand-held photo
spoof measured outside it on both signals.

Known limitations (documented in the README):
- A screen replaying a *video* of the employee produces non-rigid motion and
  is not caught by this method.
- The bands are anchored to one real deployment's camera/lighting; very
  different setups may need recalibration via FA_LIVENESS_* settings.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime

import numpy as np

from face_attendance.contracts import DetectedFace, LivenessResult, LivenessStatus

LIVENESS_METHOD = "micro-movement-v2"


class LivenessError(RuntimeError):
    """Raised when liveness input is unusable (e.g. missing landmarks)."""


@dataclass(frozen=True)
class _Observation:
    captured_at: datetime
    points: np.ndarray  # shape (5, 2), pixel coordinates


@dataclass(frozen=True)
class _Band:
    """An acceptable [low, high] range; PASSED requires falling inside it."""

    low: float
    high: float

    def contains(self, value: float) -> bool:
        return self.low <= value <= self.high

    def confidence_margin(self, value: float) -> float:
        """1.0 at the band center, 0.0 at either edge or beyond."""

        if self.high <= self.low:
            return 0.0
        center = (self.low + self.high) / 2.0
        half_width = (self.high - self.low) / 2.0
        return max(0.0, 1.0 - abs(value - center) / half_width)


class MicroMovementLivenessChecker:
    """Accumulates per-identity landmark windows and scores liveness.

    Thresholds are expressed relative to inter-ocular distance so they are
    independent of camera resolution and how close the person stands.
    """

    def __init__(
        self,
        window_size: int = 16,
        min_motion: float = 0.004,
        max_motion: float = 0.11,
        min_deformation: float = 0.003,
        max_deformation: float = 0.020,
        max_gap_seconds: float = 2.0,
    ) -> None:
        if window_size < 3:
            raise ValueError("window_size must be >= 3 for movement analysis")
        if max_gap_seconds <= 0.0:
            raise ValueError("max_gap_seconds must be > 0")
        if not 0.0 <= min_motion < max_motion:
            raise ValueError("min_motion must be >= 0 and < max_motion")
        if not 0.0 <= min_deformation < max_deformation:
            raise ValueError("min_deformation must be >= 0 and < max_deformation")
        self._window_size = window_size
        self._motion_band = _Band(min_motion, max_motion)
        self._deformation_band = _Band(min_deformation, max_deformation)
        self._max_gap_seconds = max_gap_seconds
        self._windows: dict[str, deque[_Observation]] = {}

    @property
    def window_size(self) -> int:
        return self._window_size

    def reset(self, track_id: str) -> None:
        self._windows.pop(track_id, None)

    def observe(self, track_id: str, face: DetectedFace) -> LivenessResult:
        """Add one frame of evidence for an identity and evaluate the window."""

        if face.landmarks is None:
            raise LivenessError(
                "liveness requires facial landmarks; use a detector that provides them"
            )

        points = np.array(
            [(point.x, point.y) for point in face.landmarks.as_points()],
            dtype=np.float64,
        )
        observation = _Observation(captured_at=face.frame.captured_at, points=points)

        window = self._windows.get(track_id)
        if window is None:
            window = deque(maxlen=self._window_size)
            self._windows[track_id] = window
        elif window:
            # Wall-clock gap, not frame ids: the pipeline drops stale frames
            # under load, so consecutive observations can be many frame ids
            # apart even though the person never left the camera.
            gap = (observation.captured_at - window[-1].captured_at).total_seconds()
            if gap > self._max_gap_seconds:
                # Track was lost (person left the frame); stale evidence must
                # not carry over into a new appearance.
                window.clear()
        window.append(observation)

        return self._evaluate(window)

    def _evaluate(self, window: deque[_Observation]) -> LivenessResult:
        count = len(window)
        if count < self._window_size:
            return LivenessResult(
                status=LivenessStatus.UNKNOWN,
                method=LIVENESS_METHOD,
                frame_count=count,
                confidence_score=0.0,
                reason=f"gathering evidence ({count}/{self._window_size} frames)",
            )

        stacks = np.stack([obs.points for obs in window])  # (n, 5, 2)
        scale = _mean_interocular_distance(stacks)
        if scale <= 0.0:
            return LivenessResult(
                status=LivenessStatus.FAILED,
                method=LIVENESS_METHOD,
                frame_count=count,
                confidence_score=0.0,
                reason="degenerate landmarks (eyes coincide)",
            )

        motion = _centroid_motion(stacks) / scale
        deformation = _non_rigid_deformation(stacks)

        if not self._motion_band.contains(motion):
            reason = (
                "no natural head movement detected across frames "
                "(possible mounted static photo)"
                if motion < self._motion_band.low
                else "movement is more erratic than a natural head, "
                "not just facial expression (possible hand-held photo or screen)"
            )
            return LivenessResult(
                status=LivenessStatus.FAILED,
                method=LIVENESS_METHOD,
                frame_count=count,
                confidence_score=_failure_confidence(self._motion_band, motion),
                reason=reason,
                motion=motion,
                deformation=deformation,
            )

        if not self._deformation_band.contains(deformation):
            reason = (
                "movement is rigid, face does not deform naturally "
                "(possible mounted photo or screen spoof)"
                if deformation < self._deformation_band.low
                else "shape residual is larger than natural facial movement, "
                "consistent with a tilted rigid object (possible hand-held photo)"
            )
            return LivenessResult(
                status=LivenessStatus.FAILED,
                method=LIVENESS_METHOD,
                frame_count=count,
                confidence_score=_failure_confidence(self._deformation_band, deformation),
                reason=reason,
                motion=motion,
                deformation=deformation,
            )

        confidence = 0.5 + 0.5 * min(
            self._motion_band.confidence_margin(motion),
            self._deformation_band.confidence_margin(deformation),
        )
        return LivenessResult(
            status=LivenessStatus.PASSED,
            method=LIVENESS_METHOD,
            frame_count=count,
            confidence_score=min(1.0, confidence),
            motion=motion,
            deformation=deformation,
        )


def _mean_interocular_distance(stacks: np.ndarray) -> float:
    eye_deltas = stacks[:, 0, :] - stacks[:, 1, :]  # right_eye - left_eye
    return float(np.mean(np.linalg.norm(eye_deltas, axis=1)))


def _centroid_motion(stacks: np.ndarray) -> float:
    """Median per-frame displacement of the landmark centroid, in pixels.

    Median rather than mean: a single noisy or fast-moving frame should not
    dominate the estimate of "typical" motion over the window.
    """

    centroids = stacks.mean(axis=1)  # (n, 2)
    displacements = np.linalg.norm(np.diff(centroids, axis=0), axis=1)
    return float(np.median(displacements))


def _non_rigid_deformation(stacks: np.ndarray) -> float:
    """Residual landmark movement after removing rigid motion per frame.

    Each frame's landmarks are translated to their centroid, scaled by
    inter-ocular distance, and rotated so the eye line is horizontal. What
    remains is shape change only; its per-landmark median absolute deviation
    (scaled to be std-comparable) across the window measures how much the
    face itself deformed, robust to a handful of noisy frames.
    """

    normalized = np.empty_like(stacks)
    for index in range(stacks.shape[0]):
        points = stacks[index]
        centroid = points.mean(axis=0)
        centered = points - centroid

        eye_delta = points[0] - points[1]
        scale = float(np.linalg.norm(eye_delta))
        if scale == 0.0:
            return 0.0
        scaled = centered / scale

        angle = float(np.arctan2(eye_delta[1], eye_delta[0]))
        cosine, sine = np.cos(-angle), np.sin(-angle)
        rotation = np.array([[cosine, -sine], [sine, cosine]])
        normalized[index] = scaled @ rotation.T

    median = np.median(normalized, axis=0)  # (5, 2)
    mad = np.median(np.abs(normalized - median), axis=0)  # (5, 2)
    return float(mad.mean() * 1.4826)  # scale MAD to be std-comparable


def _failure_confidence(band: _Band, value: float) -> float:
    """Low confidence-of-liveness score for failed checks, bounded to [0, 0.5)."""

    if value < band.low:
        if band.low <= 0.0:
            return 0.0
        return max(0.0, min(0.49, 0.5 * value / band.low))
    # value > band.high: confidence falls the further past the ceiling it is.
    excess = (value - band.high) / band.high if band.high > 0.0 else 1.0
    return max(0.0, min(0.49, 0.49 - 0.1 * excess))
