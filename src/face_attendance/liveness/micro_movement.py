"""Multi-frame liveness via micro-movement and non-rigidity analysis.

Evidence is gathered across a window of frames per tracked identity:

1. Motion presence — live heads are never pixel-still. A window whose
   landmark centroid barely moves (relative to face size) is treated as a
   static photo.
2. Non-rigid deformation — a waved photo or a screen showing a still image
   moves as a rigid plane. After removing translation, scale, and in-plane
   rotation from each frame's landmarks, a rigid spoof leaves near-zero
   residual movement, while a live face keeps deforming (eyes, mouth,
   perspective changes).

Known limitation (documented in the README): a screen replaying a *video*
of the employee produces non-rigid motion and is not caught by this method.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from datetime import datetime

import numpy as np

from face_attendance.contracts import DetectedFace, LivenessResult, LivenessStatus

LIVENESS_METHOD = "micro-movement-v1"


class LivenessError(RuntimeError):
    """Raised when liveness input is unusable (e.g. missing landmarks)."""


@dataclass(frozen=True)
class _Observation:
    captured_at: datetime
    points: np.ndarray  # shape (5, 2), pixel coordinates


class MicroMovementLivenessChecker:
    """Accumulates per-identity landmark windows and scores liveness.

    Thresholds are expressed relative to inter-ocular distance so they are
    independent of camera resolution and how close the person stands.
    Defaults are deliberately conservative; calibrate per deployment via
    configuration if needed.
    """

    def __init__(
        self,
        window_size: int = 12,
        min_motion: float = 0.004,
        min_deformation: float = 0.006,
        max_gap_seconds: float = 2.0,
    ) -> None:
        if window_size < 3:
            raise ValueError("window_size must be >= 3 for movement analysis")
        if max_gap_seconds <= 0.0:
            raise ValueError("max_gap_seconds must be > 0")
        self._window_size = window_size
        self._min_motion = min_motion
        self._min_deformation = min_deformation
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
        if motion < self._min_motion:
            return LivenessResult(
                status=LivenessStatus.FAILED,
                method=LIVENESS_METHOD,
                frame_count=count,
                confidence_score=_failure_confidence(motion, self._min_motion),
                reason=(
                    "no natural head movement detected across frames "
                    "(possible static photo)"
                ),
                motion=motion,
            )

        deformation = _non_rigid_deformation(stacks)
        if deformation < self._min_deformation:
            return LivenessResult(
                status=LivenessStatus.FAILED,
                method=LIVENESS_METHOD,
                frame_count=count,
                confidence_score=_failure_confidence(deformation, self._min_deformation),
                reason=(
                    "movement is rigid, face does not deform naturally "
                    "(possible photo or screen spoof)"
                ),
                motion=motion,
                deformation=deformation,
            )

        motion_margin = min(1.0, motion / (self._min_motion * 4.0))
        deformation_margin = min(1.0, deformation / (self._min_deformation * 4.0))
        confidence = 0.5 + 0.5 * min(motion_margin, deformation_margin)
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
    """Mean per-frame displacement of the landmark centroid, in pixels."""

    centroids = stacks.mean(axis=1)  # (n, 2)
    displacements = np.linalg.norm(np.diff(centroids, axis=0), axis=1)
    return float(np.mean(displacements))


def _non_rigid_deformation(stacks: np.ndarray) -> float:
    """Residual landmark movement after removing rigid motion per frame.

    Each frame's landmarks are translated to their centroid, scaled by
    inter-ocular distance, and rotated so the eye line is horizontal. What
    remains is shape change only; its per-landmark standard deviation across
    the window measures how much the face itself deformed.
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

    per_landmark_std = normalized.std(axis=0)  # (5, 2)
    return float(per_landmark_std.mean())


def _failure_confidence(value: float, threshold: float) -> float:
    """Low confidence-of-liveness score for failed checks, bounded to [0, 0.5)."""

    if threshold <= 0.0:
        return 0.0
    return max(0.0, min(0.49, 0.5 * value / threshold))
