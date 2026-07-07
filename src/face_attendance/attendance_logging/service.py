"""Attendance decisions: when a match becomes a logged clock-in/out event."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from face_attendance.contracts import (
    AttendanceEvent,
    AttendanceEventType,
    LivenessResult,
    LivenessStatus,
    MatchResult,
)
from face_attendance.storage import AttendanceStorage


class AttendanceError(RuntimeError):
    """Raised when an attendance decision cannot be completed."""


@dataclass(frozen=True)
class AttendanceDecision:
    """Outcome of attempting to log attendance for one recognized face."""

    logged: bool
    event: AttendanceEvent | None
    reason: str


class AttendanceService:
    """Turns verified matches into clock-in/clock-out events.

    Rules:
    - Only matched faces with passed liveness are ever logged.
    - Event type toggles: no history or last event clock_out -> clock_in;
      last event clock_in -> clock_out.
    - A per-employee cooldown suppresses duplicate events while someone
      stands in front of the camera.
    """

    def __init__(self, storage: AttendanceStorage, cooldown_seconds: int = 60) -> None:
        if cooldown_seconds < 0:
            raise ValueError("cooldown_seconds must be >= 0")
        self._storage = storage
        self._cooldown = timedelta(seconds=cooldown_seconds)

    def record(
        self,
        match: MatchResult,
        liveness: LivenessResult,
        now: datetime | None = None,
    ) -> AttendanceDecision:
        if not match.is_match or match.employee_id is None:
            return AttendanceDecision(False, None, "no employee match")
        if liveness.status is not LivenessStatus.PASSED:
            detail = liveness.reason or liveness.status.value
            return AttendanceDecision(False, None, f"liveness not passed: {detail}")

        occurred_at = now if now is not None else datetime.now(timezone.utc)
        if occurred_at.tzinfo is None:
            raise AttendanceError("attendance timestamps must be timezone-aware")

        employee_id = match.employee_id
        last_event = self._storage.get_last_attendance_event(employee_id)

        if last_event is not None:
            elapsed = occurred_at - last_event.occurred_at
            if elapsed < self._cooldown:
                remaining = int((self._cooldown - elapsed).total_seconds()) + 1
                return AttendanceDecision(
                    False,
                    None,
                    f"cooldown active for {employee_id}; retry in ~{remaining}s",
                )

        event_type = AttendanceEventType.CLOCK_IN
        if last_event is not None and last_event.event_type is AttendanceEventType.CLOCK_IN:
            event_type = AttendanceEventType.CLOCK_OUT

        event = AttendanceEvent(
            employee_id=employee_id,
            occurred_at=occurred_at,
            event_type=event_type,
            confidence_score=match.confidence_score,
            match_distance=match.distance,
        )
        self._storage.add_attendance_event(event)
        return AttendanceDecision(True, event, f"logged {event_type.value}")
