"""Application settings with environment-variable overrides.

Every tunable in the pipeline lives here so deployments (kiosk, office
terminal, future cloud API) configure behavior via FA_* environment
variables instead of code edits. Invalid values fail loudly at startup.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

ENV_PREFIX = "FA_"


class SettingsError(RuntimeError):
    """Raised when configuration is invalid, with the offending field named."""


class AppSettings(BaseModel):
    """Validated runtime configuration for the attendance system."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    # Paths
    database_path: Path = Path("data/attendance.db")
    models_dir: Path = Path("models")
    log_dir: Path = Path("logs")

    # Camera. Backend "auto" tries the platform default, then falls back to
    # DirectShow on Windows (some webcams open under MSMF but deliver nothing).
    camera_index: int = Field(default=0, ge=0)
    camera_backend: Literal["auto", "default", "msmf", "dshow"] = "auto"

    # Detection
    detection_score_threshold: float = Field(default=0.8, gt=0.0, le=1.0)

    # Matching (cosine similarity; see README for threshold rationale)
    similarity_threshold: float = Field(default=0.363, gt=-1.0, lt=1.0)

    # Enrollment quality gates
    enrollment_min_confidence: float = Field(default=0.85, gt=0.0, le=1.0)
    enrollment_min_face_size: int = Field(default=80, gt=0)
    enrollment_samples: int = Field(default=5, ge=1, le=20)
    enrollment_frame_gap: int = Field(default=15, ge=0)

    # Liveness
    liveness_window_size: int = Field(default=12, ge=3)
    liveness_min_motion: float = Field(default=0.004, gt=0.0)
    liveness_min_deformation: float = Field(default=0.006, gt=0.0)
    liveness_max_gap_seconds: float = Field(default=2.0, gt=0.0)

    # Attendance
    cooldown_seconds: int = Field(default=60, ge=0)
    # How often a running attend session re-reads the gallery, so enrollments
    # and deactivations made elsewhere take effect without a restart.
    index_refresh_seconds: int = Field(default=30, ge=0)

    # Logging
    log_level: str = "INFO"

    @classmethod
    def from_env(cls, environ: dict[str, str] | None = None) -> AppSettings:
        """Build settings from FA_* environment variables over defaults."""

        source = environ if environ is not None else dict(os.environ)
        overrides: dict[str, str] = {}
        known_fields = set(cls.model_fields)
        for key, value in source.items():
            if not key.startswith(ENV_PREFIX):
                continue
            field_name = key[len(ENV_PREFIX) :].lower()
            if field_name not in known_fields:
                raise SettingsError(
                    f"unknown configuration variable {key}; "
                    f"valid fields: {', '.join(sorted(known_fields))}"
                )
            overrides[field_name] = value

        try:
            return cls(**overrides)
        except ValidationError as exc:
            first = exc.errors()[0]
            location = ".".join(str(part) for part in first["loc"])
            raise SettingsError(
                f"invalid configuration value for {ENV_PREFIX}{location.upper()}: "
                f"{first['msg']}"
            ) from exc

    @property
    def yunet_model_path(self) -> Path:
        return self.models_dir / "face_detection_yunet_2023mar.onnx"

    @property
    def sface_model_path(self) -> Path:
        return self.models_dir / "face_recognition_sface_2021dec.onnx"
