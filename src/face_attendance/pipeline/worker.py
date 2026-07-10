"""Background recognition pipeline: keeps the capture loop non-blocking.

Producer/consumer design:
- The capture loop (producer) pushes every frame into a LatestFrameSlot.
- The slot holds exactly one frame; a newer frame replaces an unconsumed one.
  Backlog is therefore impossible by construction — when recognition cannot
  keep up, stale frames are dropped and the drop count is observable.
- A single RecognitionWorker thread (consumer) runs detection, embedding,
  matching, liveness, and attendance decisions off the UI thread.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    import numpy as np

from face_attendance.attendance_logging import AttendanceDecision, AttendanceService
from face_attendance.capture import Frame
from face_attendance.contracts import (
    DetectedFace,
    FrameMetadata,
    LivenessResult,
    MatchResult,
)
from face_attendance.detection.base import FaceDetector
from face_attendance.embeddings.base import EmbeddingExtractor
from face_attendance.matching import EmployeeMatcher


class PipelineError(RuntimeError):
    """Raised for unrecoverable pipeline failures."""


class LatestFrameSlot:
    """Thread-safe single-frame mailbox with stale-frame dropping."""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._frame: Frame | None = None
        self._dropped = 0

    @property
    def dropped_count(self) -> int:
        with self._condition:
            return self._dropped

    def put(self, frame: Frame) -> None:
        with self._condition:
            if self._frame is not None:
                self._dropped += 1
            self._frame = frame
            self._condition.notify()

    def get(self, timeout: float = 0.1) -> Frame | None:
        with self._condition:
            if self._frame is None:
                self._condition.wait(timeout)
            frame = self._frame
            self._frame = None
            return frame


@dataclass(frozen=True)
class FaceOutcome:
    """Everything the pipeline concluded about one face in one frame."""

    face: DetectedFace
    match: MatchResult
    liveness: LivenessResult | None = None
    decision: AttendanceDecision | None = None


@dataclass(frozen=True)
class RecognitionOutput:
    """Per-frame pipeline result delivered to the display/operator layer."""

    frame: FrameMetadata
    outcomes: list[FaceOutcome] = field(default_factory=list)
    # The exact frame pixels these outcomes were computed from. The display
    # layer draws boxes onto this image rather than whatever newer frame the
    # non-blocking capture loop has since advanced to, so labels never drift
    # onto a mismatched frame under inference lag. Excluded from equality
    # (ndarray comparison is ambiguous) and defaulted so reporting-only
    # constructions need not supply it.
    image: np.ndarray | None = field(default=None, compare=False)


class LivenessObserver:
    """Structural interface the worker needs from a liveness checker."""

    def observe(self, track_id: str, face: DetectedFace) -> LivenessResult:  # pragma: no cover
        raise NotImplementedError


class RecognitionWorker(threading.Thread):
    """Consumes frames from the slot and emits RecognitionOutputs.

    Error policy:
    - Any per-frame failure (bad frame, model hiccup, storage write) is
      reported via on_error and the worker keeps running.
    - max_consecutive_errors failures in a row means something is
      structurally broken; the worker reports a PipelineError and exits so
      the operator sees a stopped pipeline instead of a silent error loop.
    """

    def __init__(
        self,
        slot: LatestFrameSlot,
        detector: FaceDetector,
        embedder: EmbeddingExtractor,
        matcher: EmployeeMatcher,
        liveness_checker: LivenessObserver,
        attendance_service: AttendanceService,
        on_result: Callable[[RecognitionOutput], None],
        on_error: Callable[[Exception], None],
        max_consecutive_errors: int = 10,
        poll_timeout: float = 0.1,
    ) -> None:
        super().__init__(name="recognition-worker", daemon=True)
        if max_consecutive_errors < 1:
            raise ValueError("max_consecutive_errors must be >= 1")
        self._slot = slot
        self._detector = detector
        self._embedder = embedder
        self._matcher = matcher
        self._liveness = liveness_checker
        self._attendance = attendance_service
        self._on_result = on_result
        self._on_error = on_error
        self._max_consecutive_errors = max_consecutive_errors
        self._poll_timeout = poll_timeout
        self._stop_event = threading.Event()
        self._processed_count = 0

    @property
    def processed_count(self) -> int:
        return self._processed_count

    def stop(self, join_timeout: float = 5.0) -> None:
        """Request shutdown and wait for the worker to finish."""

        self._stop_event.set()
        if self.is_alive():
            self.join(join_timeout)
            if self.is_alive():
                raise PipelineError("recognition worker did not stop within timeout")

    def run(self) -> None:
        consecutive_errors = 0
        while not self._stop_event.is_set():
            frame = self._slot.get(timeout=self._poll_timeout)
            if frame is None:
                continue
            try:
                output = self._process_frame(frame)
            except Exception as exc:  # noqa: BLE001 - single supervision point
                consecutive_errors += 1
                self._on_error(exc)
                if consecutive_errors >= self._max_consecutive_errors:
                    self._on_error(
                        PipelineError(
                            f"worker stopping after {consecutive_errors} "
                            "consecutive frame failures"
                        )
                    )
                    return
                continue
            consecutive_errors = 0
            self._processed_count += 1
            self._on_result(output)

    def _process_frame(self, frame: Frame) -> RecognitionOutput:
        outcomes: list[FaceOutcome] = []
        for face in self._detector.detect(frame):
            embedding = self._embedder.extract(frame, face)
            match = self._matcher.match(embedding)

            liveness: LivenessResult | None = None
            decision: AttendanceDecision | None = None
            if match.is_match and match.employee_id is not None:
                liveness = self._liveness.observe(match.employee_id, face)
                decision = self._attendance.record(match, liveness)

            outcomes.append(
                FaceOutcome(face=face, match=match, liveness=liveness, decision=decision)
            )
        return RecognitionOutput(
            frame=frame.metadata, outcomes=outcomes, image=frame.image
        )
