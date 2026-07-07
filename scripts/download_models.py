"""Download the pinned ONNX models used for detection and embeddings.

Thin wrapper around face_attendance.model_files.

Usage:
    python scripts/download_models.py [--models-dir models]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from face_attendance.model_files import ModelDownloadError, download_all_models


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--models-dir",
        type=Path,
        default=Path("models"),
        help="directory to store the ONNX models (default: models/)",
    )
    args = parser.parse_args(argv)

    try:
        download_all_models(args.models_dir)
    except ModelDownloadError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
