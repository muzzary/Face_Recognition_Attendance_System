"""Interactive enrollment flow: collect quality samples, persist embeddings."""

from __future__ import annotations

import logging
from typing import Callable

from face_attendance.app.factory import PipelineComponents
from face_attendance.capture import FrameSource
from face_attendance.contracts import EmployeeRecord, FaceEmbedding
from face_attendance.embeddings import EnrollmentError

logger = logging.getLogger(__name__)


def run_enrollment(
    components: PipelineComponents,
    frame_source: FrameSource,
    employee_id: str,
    full_name: str,
    on_message: Callable[[str], None] = print,
    max_frames: int = 1500,
) -> EmployeeRecord:
    """Collect enrollment samples from the frame source and persist them.

    Samples are spaced by a frame gap so the operator can vary pose slightly,
    which makes the stored gallery more robust. Raises EnrollmentError if the
    frame budget runs out before enough good samples are captured.
    """

    settings = components.settings
    service = components.enrollment
    required = service.required_samples
    gap = settings.enrollment_frame_gap

    if components.storage.get_employee(settings.org_id, employee_id) is not None:
        raise EnrollmentError(f"employee {employee_id} is already enrolled")

    samples: list[FaceEmbedding] = []
    frames_since_sample = gap  # allow an immediate first sample
    last_feedback = ""

    on_message(
        f"Enrolling {full_name} ({employee_id}): need {required} samples. "
        "Look at the camera and turn your head slightly between captures."
    )

    for _ in range(max_frames):
        frame = frame_source.read()
        frames_since_sample += 1
        if frames_since_sample <= gap:
            continue

        try:
            sample = service.capture_sample(frame)
        except EnrollmentError as exc:
            # Per-frame quality feedback; only repeat when the reason changes.
            feedback = str(exc)
            if feedback != last_feedback:
                on_message(f"  waiting: {feedback}")
                last_feedback = feedback
            continue

        samples.append(sample)
        frames_since_sample = 0
        last_feedback = ""
        on_message(f"  captured sample {len(samples)}/{required}")

        if len(samples) >= required:
            employee = service.enroll(employee_id, full_name, samples)
            components.index.refresh_from_storage(components.storage)
            on_message(
                f"Enrolled {full_name} ({employee_id}) with {len(samples)} samples."
            )
            logger.info("enrolled employee %s with %d samples", employee_id, len(samples))
            return employee

    raise EnrollmentError(
        f"could not capture {required} good samples in {max_frames} frames; "
        "check lighting and camera position, then retry"
    )
