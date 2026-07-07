"""Remember which camera backend worked so later launches skip the probe.

On machines whose webcam ignores the default backend (e.g. MSMF-silent
cameras on Windows), the first "auto" open pays a 10-20 s probe before
falling back. Caching the discovered backend makes every later launch open
in about a second. The cache is a plain JSON file next to the database and
is purely an optimization: corruption or IO failure just means one slow,
self-healing open.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from face_attendance.capture.camera import CaptureError, OpenCvCamera

logger = logging.getLogger(__name__)

_CACHEABLE_BACKENDS = {"default", "msmf", "dshow"}


def load_cached_backend(cache_path: Path, camera_index: int) -> str | None:
    try:
        raw = json.loads(cache_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("ignoring unreadable camera backend cache: %s", exc)
        return None
    value = raw.get(str(camera_index)) if isinstance(raw, dict) else None
    return value if value in _CACHEABLE_BACKENDS else None


def store_cached_backend(cache_path: Path, camera_index: int, backend: str) -> None:
    if backend not in _CACHEABLE_BACKENDS:
        return
    entries: dict[str, str] = {}
    try:
        existing = json.loads(cache_path.read_text(encoding="utf-8"))
        if isinstance(existing, dict):
            entries = {k: v for k, v in existing.items() if isinstance(v, str)}
    except (OSError, json.JSONDecodeError):
        pass
    entries[str(camera_index)] = backend
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(entries, indent=0), encoding="utf-8")
    except OSError as exc:
        logger.warning("could not persist camera backend cache: %s", exc)


def open_camera_remembering_backend(
    camera_index: int, configured_backend: str, cache_path: Path
) -> OpenCvCamera:
    """Open the camera, using and maintaining the backend cache for "auto".

    A cached backend that stopped working (camera swapped, driver update) is
    discarded and the full auto probe runs again, refreshing the cache.
    """

    if configured_backend != "auto":
        camera = OpenCvCamera(camera_index=camera_index, backend=configured_backend)
        camera.open()
        return camera

    cached = load_cached_backend(cache_path, camera_index)
    if cached is not None:
        camera = OpenCvCamera(camera_index=camera_index, backend=cached)
        try:
            camera.open()
            return camera
        except CaptureError as exc:
            logger.warning(
                "cached %s backend no longer works (%s); re-probing", cached, exc
            )

    camera = OpenCvCamera(camera_index=camera_index, backend="auto")
    camera.open()
    if camera.backend_used is not None and camera.backend_used != cached:
        store_cached_backend(cache_path, camera_index, camera.backend_used)
    return camera
