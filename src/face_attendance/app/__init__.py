"""Application flows: wiring, enrollment, attendance, and reports."""

from face_attendance.app.attend import AttendStats, draw_overlay, run_attendance
from face_attendance.app.calibrate import (
    CalibrationResult,
    print_calibration_report,
    run_liveness_calibration,
)
from face_attendance.app.enroll import run_enrollment
from face_attendance.app.factory import PipelineComponents, build_components
from face_attendance.app.report import print_attendance_report, print_employees

__all__ = [
    "AttendStats",
    "CalibrationResult",
    "PipelineComponents",
    "build_components",
    "draw_overlay",
    "print_attendance_report",
    "print_calibration_report",
    "print_employees",
    "run_attendance",
    "run_enrollment",
    "run_liveness_calibration",
]
