"""Application settings with environment-variable overrides.

Every tunable in the pipeline lives here so deployments (kiosk, office
terminal, future cloud API) configure behavior via FA_* environment
variables instead of code edits. Invalid values fail loudly at startup.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

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

    # Organization (tenant). Every row this terminal reads or writes is scoped
    # to this org. The CLI is single-org today, so it defaults to the built-in
    # "default" organization (matches storage.DEFAULT_ORG_ID); a deployment
    # running for a specific company sets FA_ORG_ID to that company's id.
    org_id: str = Field(default="default", min_length=1)

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

    # Liveness. Motion is an acceptable [min, max] band: a live face's
    # natural range (including normal head turns) sits inside it, a mounted
    # static photo falls below it, a hand-held photo (tremor + tilt) falls
    # above it. Deformation is a floor only - a ceiling was tried and proved
    # wrong on real hardware (natural head turns are ALSO an out-of-plane
    # rotation the in-plane-only correction can't remove, so it false-
    # rejected live users). Defaults anchored to real measured data - see
    # docs/phase-log.md.
    liveness_window_size: int = Field(default=16, ge=3)
    liveness_min_motion: float = Field(default=0.004, ge=0.0)
    liveness_max_motion: float = Field(default=0.11, gt=0.0)
    liveness_min_deformation: float = Field(default=0.003, ge=0.0)
    liveness_max_gap_seconds: float = Field(default=2.0, gt=0.0)

    # Live stream lifecycle. The API opens the camera lazily on the first
    # /stream request (a cold start can take 60-90s on Windows) and auto-stops
    # it after this many seconds with zero active viewers, so an unwatched API
    # process stops reserving the single camera and burning recognition CPU. A
    # new viewer within the window cancels the pending stop and keeps serving
    # from the still-open camera. Default 5 minutes balances the cold-start cost
    # against not holding the device open indefinitely for nobody.
    stream_idle_timeout_seconds: float = Field(default=300.0, gt=0.0)

    # Attendance
    cooldown_seconds: int = Field(default=60, ge=0)
    # How often a running attend session re-reads the gallery, so enrollments
    # and deactivations made elsewhere take effect without a restart.
    index_refresh_seconds: int = Field(default=30, ge=0)

    # Auth. Secret used to sign/verify API JWTs. It is a real secret, so it has
    # no usable default: unset (None) means "not configured", and the API auth
    # layer fails loudly the moment it needs to issue or verify a token (see
    # api.auth.require_jwt_secret). Left optional here so camera-only CLI usage,
    # which never touches auth, doesn't have to carry an API secret.
    jwt_secret: str | None = Field(default=None, min_length=32)

    # Logging
    log_level: str = "INFO"

    @model_validator(mode="after")
    def require_valid_liveness_bands(self) -> AppSettings:
        if self.liveness_min_motion >= self.liveness_max_motion:
            raise ValueError(
                "liveness_min_motion must be < liveness_max_motion"
            )
        return self

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
