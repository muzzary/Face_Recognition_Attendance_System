"""Validated data contracts shared across attendance pipeline boundaries."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from math import isfinite

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    """Base model for immutable boundary payloads with no surprise fields."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class AttendanceEventType(str, Enum):
    """Supported attendance event types."""

    CLOCK_IN = "clock_in"
    CLOCK_OUT = "clock_out"


class LivenessStatus(str, Enum):
    """Possible outcomes from a liveness check."""

    PASSED = "passed"
    FAILED = "failed"
    UNKNOWN = "unknown"


class FrameMetadata(StrictModel):
    """Metadata that describes a camera frame without storing image bytes."""

    frame_id: int = Field(ge=0)
    camera_id: str = Field(min_length=1)
    captured_at: datetime
    width: int = Field(gt=0)
    height: int = Field(gt=0)

    @field_validator("captured_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("captured_at must be timezone-aware")
        return value.astimezone(timezone.utc)


class BoundingBox(StrictModel):
    """Face location in pixel coordinates."""

    x: int = Field(ge=0)
    y: int = Field(ge=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class Point(StrictModel):
    """A sub-pixel image coordinate."""

    x: float
    y: float

    @field_validator("x", "y")
    @classmethod
    def require_finite(cls, value: float) -> float:
        if not isfinite(value):
            raise ValueError("landmark coordinates must be finite")
        return value


class FaceLandmarks(StrictModel):
    """Five-point facial landmarks in YuNet order."""

    right_eye: Point
    left_eye: Point
    nose_tip: Point
    mouth_right: Point
    mouth_left: Point

    def as_points(self) -> tuple[Point, Point, Point, Point, Point]:
        return (
            self.right_eye,
            self.left_eye,
            self.nose_tip,
            self.mouth_right,
            self.mouth_left,
        )


class DetectedFace(StrictModel):
    """A detected face and its confidence in a specific frame."""

    frame: FrameMetadata
    bounding_box: BoundingBox
    detection_confidence: float = Field(ge=0.0, le=1.0)
    landmarks: FaceLandmarks | None = None


class FaceEmbedding(StrictModel):
    """Numeric face embedding produced by an embedding model."""

    org_id: str = Field(min_length=1)
    vector: list[float] = Field(min_length=1)
    dimensions: int = Field(gt=0)
    model_name: str = Field(min_length=1)

    @field_validator("vector")
    @classmethod
    def require_finite_values(cls, value: list[float]) -> list[float]:
        if not all(isfinite(item) for item in value):
            raise ValueError("embedding vector must contain only finite values")
        return value

    @model_validator(mode="after")
    def require_dimension_match(self) -> FaceEmbedding:
        if len(self.vector) != self.dimensions:
            raise ValueError("embedding dimensions must match vector length")
        return self


class EmployeeRecord(StrictModel):
    """Employee metadata stored alongside one or more embeddings."""

    org_id: str = Field(min_length=1)
    employee_id: str = Field(min_length=1)
    full_name: str = Field(min_length=1)
    is_active: bool = True
    created_at: datetime

    @field_validator("created_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        return value.astimezone(timezone.utc)


class MatchResult(StrictModel):
    """Result of comparing a live embedding with stored employee embeddings."""

    is_match: bool
    employee_id: str | None = None
    distance: float = Field(ge=0.0)
    threshold: float = Field(ge=0.0)
    confidence_score: float = Field(ge=0.0, le=1.0)

    @model_validator(mode="after")
    def require_employee_for_match(self) -> MatchResult:
        if self.is_match and not self.employee_id:
            raise ValueError("employee_id is required when is_match is true")
        if not self.is_match and self.employee_id is not None:
            raise ValueError("employee_id must be omitted when is_match is false")
        return self


class LivenessResult(StrictModel):
    """Outcome of a multi-frame liveness check."""

    status: LivenessStatus
    method: str = Field(min_length=1)
    frame_count: int = Field(gt=0)
    confidence_score: float = Field(ge=0.0, le=1.0)
    reason: str | None = None
    # Raw measured signals (None until a full evidence window exists), kept
    # so real deployments can observe and calibrate FA_LIVENESS_* thresholds
    # against actual camera/lighting conditions instead of guessing.
    motion: float | None = Field(default=None, ge=0.0)
    deformation: float | None = Field(default=None, ge=0.0)

    @model_validator(mode="after")
    def require_reason_for_failure(self) -> LivenessResult:
        if self.status == LivenessStatus.FAILED and not self.reason:
            raise ValueError("reason is required when liveness fails")
        return self


class AttendanceEvent(StrictModel):
    """Secure attendance log payload with no image data."""

    org_id: str = Field(min_length=1)
    employee_id: str = Field(min_length=1)
    occurred_at: datetime
    event_type: AttendanceEventType
    confidence_score: float = Field(ge=0.0, le=1.0)
    match_distance: float = Field(ge=0.0)

    @field_validator("occurred_at")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("occurred_at must be timezone-aware")
        return value.astimezone(timezone.utc)

