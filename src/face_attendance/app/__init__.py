"""Application flows: wiring, enrollment, attendance, and reports."""

from face_attendance.app.attend import AttendStats, run_attendance
from face_attendance.app.enroll import run_enrollment
from face_attendance.app.factory import PipelineComponents, build_components
from face_attendance.app.report import print_attendance_report, print_employees

__all__ = [
    "AttendStats",
    "PipelineComponents",
    "build_components",
    "print_attendance_report",
    "print_employees",
    "run_attendance",
    "run_enrollment",
]
