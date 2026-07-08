"""Attendance mode: live camera loop feeding the background pipeline."""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable

from face_attendance.app.factory import PipelineComponents
from face_attendance.capture import CaptureError, Frame, FrameSource
from face_attendance.contracts import LivenessResult, LivenessStatus
from face_attendance.pipeline import (
    LatestFrameSlot,
    PipelineError,
    RecognitionOutput,
    RecognitionWorker,
)

logger = logging.getLogger(__name__)

WINDOW_TITLE = "Face Attendance (press q to quit)"


@dataclass
class AttendStats:
    """Operator-facing counters for one attendance session."""

    frames_read: int = 0
    frames_processed: int = 0
    frames_dropped: int = 0
    events_logged: int = 0
    pipeline_failed: bool = False


def run_attendance(
    components: PipelineComponents,
    frame_source: FrameSource,
    display: bool = False,
    on_message: Callable[[str], None] = print,
    max_frames: int | None = None,
) -> AttendStats:
    """Run the attendance loop until quit, camera loss, or max_frames.

    The capture loop stays lightweight: read, hand off to the worker via the
    latest-frame slot, draw the most recent results. All recognition work
    happens on the worker thread.
    """

    stats = AttendStats()
    slot = LatestFrameSlot()
    # Both deques cross the worker/main thread boundary; every access is
    # lock-protected (an unsynchronized iteration during append raises).
    shared_lock = threading.Lock()
    outputs: deque[RecognitionOutput] = deque(maxlen=64)
    worker_errors: deque[Exception] = deque(maxlen=16)

    def on_result(output: RecognitionOutput) -> None:
        with shared_lock:
            outputs.append(output)

    def on_error(error: Exception) -> None:
        with shared_lock:
            worker_errors.append(error)
        logger.error("pipeline error: %s", error)

    if components.index.size == 0:
        on_message(
            "warning: no enrolled employees in the database; "
            "every face will be reported as unknown"
        )

    worker = RecognitionWorker(
        slot=slot,
        detector=components.detector,
        embedder=components.embedder,
        matcher=components.matcher,
        liveness_checker=components.liveness,
        attendance_service=components.attendance,
        on_result=on_result,
        on_error=on_error,
    )
    worker.start()

    last_message_per_employee: dict[str, str] = {}
    latest_output: RecognitionOutput | None = None
    refresh_interval = components.settings.index_refresh_seconds
    last_refresh = time.monotonic()

    def drain_outputs() -> None:
        nonlocal latest_output
        with shared_lock:
            drained = list(outputs)
            outputs.clear()
        if drained:
            latest_output = drained[-1]
        for output in drained:
            _report_output(output, stats, last_message_per_employee, on_message)

    try:
        while max_frames is None or stats.frames_read < max_frames:
            try:
                frame = frame_source.read()
            except CaptureError as exc:
                if max_frames is not None:
                    break  # test frame sources simply run out of frames
                on_message(f"camera failure: {exc}")
                break
            stats.frames_read += 1
            slot.put(frame)

            drain_outputs()

            with shared_lock:
                fatal = any(isinstance(e, PipelineError) for e in worker_errors)
            if fatal or not worker.is_alive():
                stats.pipeline_failed = True
                on_message(
                    "recognition pipeline stopped unexpectedly; see logs for details"
                )
                break

            # Pick up enrollments/deactivations made by other processes so a
            # deactivated employee stops matching without a terminal restart.
            if refresh_interval >= 0 and (
                time.monotonic() - last_refresh >= refresh_interval
            ):
                try:
                    components.index.refresh_from_storage(components.storage)
                except Exception as exc:  # noqa: BLE001 - keep the session alive
                    logger.error("gallery refresh failed: %s", exc)
                last_refresh = time.monotonic()

            if display and not _show_frame(frame, latest_output, components):
                break
    finally:
        try:
            worker.stop()
        except PipelineError as exc:
            # A wedged worker must not prevent camera/window cleanup.
            logger.error("worker shutdown failed: %s", exc)
            stats.pipeline_failed = True
        # Report results that landed between the last read and shutdown, so a
        # clock-in during the final instant is still shown to the operator.
        drain_outputs()
        frame_source.close()
        if display:
            _close_windows()

    stats.frames_processed = worker.processed_count
    stats.frames_dropped = slot.dropped_count
    on_message(
        f"session ended: {stats.frames_read} frames read, "
        f"{stats.frames_processed} processed, {stats.frames_dropped} dropped stale, "
        f"{stats.events_logged} attendance events logged"
    )
    return stats


def _report_output(
    output: RecognitionOutput,
    stats: AttendStats,
    last_messages: dict[str, str],
    on_message: Callable[[str], None],
) -> None:
    """Print each decision once instead of spamming per frame."""

    for outcome in output.outcomes:
        if outcome.decision is not None and outcome.decision.logged:
            event = outcome.decision.event
            assert event is not None
            stats.events_logged += 1
            on_message(
                f"{event.event_type.value.upper()}: {event.employee_id} at "
                f"{event.occurred_at.isoformat(timespec='seconds')} "
                f"(confidence {event.confidence_score:.2f})"
                f"{_liveness_metrics_suffix(outcome.liveness)}"
            )
            last_messages.pop(event.employee_id, None)
        elif outcome.match.is_match and outcome.match.employee_id is not None:
            employee_id = outcome.match.employee_id
            reason = (
                outcome.decision.reason
                if outcome.decision is not None
                else (outcome.liveness.reason if outcome.liveness else "processing")
            ) or "processing"
            # Dedupe on the stable reason text only; the metrics suffix is
            # appended to what's printed so a threshold-tuning session still
            # gets one representative sample per state instead of a spam
            # stream of frame-to-frame noise.
            if last_messages.get(employee_id) != reason:
                on_message(
                    f"{employee_id}: {reason}{_liveness_metrics_suffix(outcome.liveness)}"
                )
                last_messages[employee_id] = reason


def _liveness_metrics_suffix(liveness: LivenessResult | None) -> str:
    """Raw motion/deformation values, for FA_LIVENESS_* threshold calibration."""

    if liveness is None or liveness.motion is None:
        return ""
    parts = [f"motion={liveness.motion:.4f}"]
    if liveness.deformation is not None:
        parts.append(f"deform={liveness.deformation:.4f}")
    return " [" + ", ".join(parts) + "]"


def _show_frame(
    frame: Frame,
    latest_output: RecognitionOutput | None,
    components: PipelineComponents,
) -> bool:
    """Draw overlays and pump the UI; returns False when the user quits."""

    import cv2

    image = frame.image.copy()
    if latest_output is not None:
        for outcome in latest_output.outcomes:
            box = outcome.face.bounding_box
            if outcome.decision is not None and outcome.decision.logged:
                color = (0, 200, 0)
            elif outcome.liveness is not None and (
                outcome.liveness.status is LivenessStatus.FAILED
            ):
                color = (0, 0, 230)
            elif outcome.match.is_match:
                color = (0, 200, 230)
            else:
                color = (180, 180, 180)
            label = (
                f"{outcome.match.employee_id} {outcome.match.confidence_score:.2f}"
                if outcome.match.is_match
                else "unknown"
            )
            cv2.rectangle(
                image, (box.x, box.y), (box.x + box.width, box.y + box.height), color, 2
            )
            cv2.putText(
                image,
                label,
                (box.x, max(0, box.y - 8)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                color,
                2,
            )
    cv2.imshow(WINDOW_TITLE, image)
    return (cv2.waitKey(1) & 0xFF) != ord("q")


def _close_windows() -> None:
    import cv2

    cv2.destroyAllWindows()
