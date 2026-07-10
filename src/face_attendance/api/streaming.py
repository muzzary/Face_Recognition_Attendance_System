"""Shared MJPEG streaming primitives for the API and the standalone CLI proof.

Phase 1 proved a slow HTTP client can never back up the recognition worker: the
camera pipeline drops stale frames (``LatestFrameSlot``) and the HTTP side uses
the same latest-frame-wins discipline (``LatestJpegFrame``). This module lifts
those primitives out of ``scripts/stream_preview.py`` so both the standalone
script and the authenticated FastAPI route (Phase 7) drive the exact same code
instead of duplicating it.

``CameraStreamer`` owns the camera + recognition worker for a process's whole
lifetime (the API needs this - one process, one camera, many HTTP viewers),
publishing each annotated frame into a ``LatestJpegFrame`` that any number of
``mjpeg_stream`` consumers read without ever stalling the producer.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterator

from face_attendance.capture import CaptureError, Frame, FrameSource
from face_attendance.config import AppSettings

logger = logging.getLogger(__name__)

# Multipart boundary marker separating JPEG parts in the stream.
BOUNDARY = "faframe"


class LatestJpegFrame:
    """Latest-wins broadcast holder for encoded JPEG frames.

    Mirrors ``LatestFrameSlot``'s discipline on the HTTP side: ``put`` overwrites
    the stored frame and bumps a version counter; a consumer that fell behind
    simply receives the newest frame on its next ``get_after`` call, never a
    queued backlog. ``put`` only briefly holds the lock and never blocks, so a
    slow HTTP client can never stall the producer.
    """

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._jpeg: bytes | None = None
        self._version = 0

    @property
    def version(self) -> int:
        with self._condition:
            return self._version

    def put(self, jpeg: bytes) -> None:
        with self._condition:
            self._jpeg = jpeg
            self._version += 1
            self._condition.notify_all()

    def get_after(
        self, last_version: int, timeout: float = 1.0
    ) -> tuple[bytes, int] | None:
        """Return ``(jpeg, version)`` for the latest frame newer than last_version.

        Waits up to ``timeout`` for a newer frame, returning ``None`` on timeout
        so a caller can re-check a stop flag. Any frames produced while the
        caller was busy are skipped -- latest-wins, never a backlog.
        """

        with self._condition:
            if self._version <= last_version:
                self._condition.wait(timeout)
            if self._jpeg is None or self._version <= last_version:
                return None
            return self._jpeg, self._version


def encode_jpeg(image) -> bytes:
    """Encode a BGR numpy image as JPEG bytes."""

    import cv2

    ok, buffer = cv2.imencode(".jpg", image)
    if not ok:
        raise RuntimeError("cv2.imencode failed to encode frame as JPEG")
    return buffer.tobytes()


def mjpeg_chunk(jpeg: bytes) -> bytes:
    """Wrap one JPEG as a ``multipart/x-mixed-replace`` part."""

    return (
        b"--" + BOUNDARY.encode("ascii") + b"\r\n"
        b"Content-Type: image/jpeg\r\n"
        b"Content-Length: " + str(len(jpeg)).encode("ascii") + b"\r\n\r\n"
        + jpeg + b"\r\n"
    )


def mjpeg_stream(
    holder: LatestJpegFrame, stop_event: threading.Event
) -> Iterator[bytes]:
    """Yield ``multipart/x-mixed-replace`` chunks of the newest frame, latest-wins.

    A slow HTTP client only ever falls behind to the newest frame; it never
    backs up the producer (the holder drops stale frames). The loop wakes at
    least once a second so it notices ``stop_event`` and ends cleanly on
    shutdown rather than hanging a connected viewer forever.
    """

    last_version = 0
    while not stop_event.is_set():
        result = holder.get_after(last_version, timeout=1.0)
        if result is None:
            continue
        jpeg, last_version = result
        yield mjpeg_chunk(jpeg)


class _StoppableFrameSource:
    """Wraps an open camera so the recognition loop exits promptly on shutdown.

    ``run_attendance`` has no external stop flag - it loops until the source
    raises. Raising ``CaptureError`` once the stop event is set lets the owner
    tear the loop down cleanly (the loop then closes the underlying camera in
    its own ``finally``).
    """

    def __init__(self, source: FrameSource, stop_event: threading.Event) -> None:
        self._source = source
        self._stop_event = stop_event

    def read(self) -> Frame:
        if self._stop_event.is_set():
            raise CaptureError("stream stopping")
        return self._source.read()

    def close(self) -> None:
        self._source.close()


class CameraStreamer:
    """Owns the camera + recognition worker, publishing annotated JPEG frames.

    A single instance runs the capture/recognition loop on a background thread
    for the process's lifetime and feeds every annotated frame into
    ``jpeg_frame``. ``start`` opens the camera on the calling thread and raises
    on camera/model failure, so the caller picks its own error policy: the API
    lifespan logs a warning and leaves the feed unavailable (the rest of the API
    keeps working); the CLI proof lets it fail loud.
    """

    def __init__(self, settings: AppSettings, camera_index: int | None = None) -> None:
        self._settings = settings
        self._camera_index = camera_index
        self.jpeg_frame = LatestJpegFrame()
        self.stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def available(self) -> bool:
        """True while the recognition loop is actually running."""

        return self._thread is not None and self._thread.is_alive()

    @property
    def org_id(self) -> str:
        """Organization whose gallery and attendance writer this camera uses."""

        return self._settings.org_id

    def start(self) -> None:
        """Open the camera and run the recognition loop on a background thread."""

        # Imported lazily so the streaming primitives above stay free of the
        # camera/model import chain (unit tests never construct real hardware).
        from face_attendance.app import build_components, draw_overlay, run_attendance
        from face_attendance.cli import _make_camera, _require_models

        _require_models(self._settings)
        components = build_components(self._settings)
        camera = _make_camera(self._settings, self._camera_index)
        source = _StoppableFrameSource(camera, self.stop_event)

        def on_frame(frame, output) -> None:
            # Encode on the capture thread. The holder is latest-wins, so this
            # never blocks on HTTP clients and the recognition worker (a
            # separate thread) is never touched here.
            self.jpeg_frame.put(encode_jpeg(draw_overlay(frame, output)))

        def run() -> None:
            try:
                run_attendance(
                    components,
                    source,
                    display=False,
                    on_message=lambda _message: None,
                    on_frame=on_frame,
                )
            except Exception:  # noqa: BLE001 - last-resort guard for the bg thread
                logger.exception("live stream recognition loop crashed")

        self._thread = threading.Thread(target=run, name="api-stream", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Signal the loop to stop and wait briefly for the thread to finish."""

        self.stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
