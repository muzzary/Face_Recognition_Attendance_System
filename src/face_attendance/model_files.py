"""Pinned ONNX model specifications and hash-verified download logic.

Standard library only. Files are verified against pinned SHA256 hashes so a
corrupted or tampered download never reaches the recognition pipeline.
"""

from __future__ import annotations

import hashlib
import tempfile
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

_ZOO = "https://github.com/opencv/opencv_zoo/raw/main/models"


class ModelDownloadError(RuntimeError):
    """Raised when a model cannot be downloaded or fails hash verification."""


@dataclass(frozen=True)
class ModelSpec:
    filename: str
    url: str
    sha256: str


MODEL_SPECS: tuple[ModelSpec, ...] = (
    ModelSpec(
        filename="face_detection_yunet_2023mar.onnx",
        url=f"{_ZOO}/face_detection_yunet/face_detection_yunet_2023mar.onnx",
        sha256="8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4",
    ),
    ModelSpec(
        filename="face_recognition_sface_2021dec.onnx",
        url=f"{_ZOO}/face_recognition_sface/face_recognition_sface_2021dec.onnx",
        sha256="0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79",
    ),
)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_model(
    spec: ModelSpec,
    models_dir: Path,
    report: Callable[[str], None] = print,
) -> Path:
    """Download one model unless a verified copy already exists."""

    models_dir.mkdir(parents=True, exist_ok=True)
    target = models_dir / spec.filename

    if target.is_file():
        if file_sha256(target) == spec.sha256:
            report(f"[skip] {spec.filename} already present and verified")
            return target
        report(f"[redo] {spec.filename} exists but hash mismatches; re-downloading")
        target.unlink()

    report(f"[get ] {spec.filename} from {spec.url}")
    try:
        with urllib.request.urlopen(spec.url, timeout=120) as response:
            data = response.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise ModelDownloadError(f"failed to download {spec.url}: {exc}") from exc

    actual = hashlib.sha256(data).hexdigest()
    if actual != spec.sha256:
        raise ModelDownloadError(
            f"hash mismatch for {spec.filename}: expected {spec.sha256}, got {actual}"
        )

    # Write to a temp file then rename so a partial write never looks valid.
    with tempfile.NamedTemporaryFile(dir=models_dir, delete=False) as handle:
        handle.write(data)
        temp_path = Path(handle.name)
    temp_path.replace(target)
    report(f"[ok  ] {spec.filename} verified ({len(data)} bytes)")
    return target


def download_all_models(
    models_dir: Path, report: Callable[[str], None] = print
) -> list[Path]:
    return [download_model(spec, models_dir, report) for spec in MODEL_SPECS]
