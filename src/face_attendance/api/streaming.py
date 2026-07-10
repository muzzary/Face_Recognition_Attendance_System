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
    and feeds every annotated frame into ``jpeg_frame``. ``start`` opens the
    camera on the calling thread and raises on camera/model failure, so the
    caller picks its own error policy: the CLI proof calls ``start`` eagerly and
    lets it fail loud.

    The API instead drives the camera lazily through ``ensure_started`` and
    ``viewer_stream``: the camera opens on the *first* stream request (not at
    process startup) and auto-stops after ``idle_timeout_seconds`` with zero
    active viewers, so an unwatched API neither reserves the single camera
    device nor burns recognition CPU. Because a Windows cold start can take
    60-90s, the last viewer leaving arms an idle countdown rather than stopping
    at once; a new viewer arriving within the window cancels it and keeps
    serving from the still-open camera. All start/stop/viewer/timer state is
    serialized under one lock so a firing idle timer can never double-stop a
    camera a fresh viewer just reopened.
    """

    def __init__(
        self,
        settings: AppSettings,
        camera_index: int | None = None,
        idle_timeout_seconds: float | None = None,
    ) -> None:
        self._settings = settings
        self._camera_index = camera_index
        self._idle_timeout = (
            idle_timeout_seconds
            if idle_timeout_seconds is not None
            else settings.stream_idle_timeout_seconds
        )
        self.jpeg_frame = LatestJpegFrame()
        self.stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        # Serializes start/stop/viewer-count/idle-timer transitions.
        self._lock = threading.Lock()
        self._viewers = 0
        self._idle_timer: threading.Timer | None = None

    @property
    def available(self) -> bool:
        """True while the recognition loop is actually running."""

        return self._thread is not None and self._thread.is_alive()

    @property
    def org_id(self) -> str:
        """Organization whose gallery and attendance writer this camera uses."""

        return self._settings.org_id

    def ensure_started(self) -> None:
        """Open the camera lazily on first use; idempotent and thread-safe.

        Cancels any pending idle-stop, then starts the recognition loop if it is
        not already running. Blocks the calling thread through the cold start
        (60-90s worst case on Windows) when the camera is not yet open; a second
        request arriving during that window waits on the lock, then sees the
        camera already running and returns at once. Raises the same
        camera/model errors ``start`` raises so the route can turn them into a
        503 instead of a live feed.

        A camera opened here but never actually streamed (e.g. the client
        disconnects mid cold-start so ``viewer_stream`` never runs) is still
        bounded: an idle timer is armed whenever no viewer is counted, so an
        orphaned camera stops on its own after the idle window.
        """

        with self._lock:
            self._cancel_idle_timer_locked()
            if self._thread is None or not self._thread.is_alive():
                # A prior idle-stop leaves stop_event set; clear it so the fresh
                # recognition loop (and its frame source) is not torn down at once.
                self.stop_event.clear()
                self.start()
            if self._viewers == 0:
                self._arm_idle_timer_locked()

    def viewer_stream(self) -> Iterator[bytes]:
        """MJPEG generator for one HTTP viewer, tracked for the idle lifecycle.

        Counts this viewer in on entry (cancelling any pending idle-stop) and
        out in a ``finally`` on client disconnect/shutdown; when the last viewer
        leaves it arms the idle countdown. Delegates the actual framing to the
        shared ``mjpeg_stream`` so the latest-frame-wins/non-blocking guarantees
        are unchanged.
        """

        self._viewer_started()
        try:
            yield from mjpeg_stream(self.jpeg_frame, self.stop_event)
        finally:
            self._viewer_ended()

    def _viewer_started(self) -> None:
        with self._lock:
            self._cancel_idle_timer_locked()
            self._viewers += 1

    def _viewer_ended(self) -> None:
        with self._lock:
            self._viewers = max(0, self._viewers - 1)
            if self._viewers == 0:
                self._arm_idle_timer_locked()

    def _arm_idle_timer_locked(self) -> None:
        """Schedule an idle-stop; caller holds the lock."""

        self._cancel_idle_timer_locked()
        timer = threading.Timer(self._idle_timeout, lambda: self._on_idle_timeout(timer))
        timer.daemon = True
        self._idle_timer = timer
        timer.start()

    def _cancel_idle_timer_locked(self) -> None:
        if self._idle_timer is not None:
            self._idle_timer.cancel()
            self._idle_timer = None

    def _on_idle_timeout(self, timer: threading.Timer) -> None:
        """Stop the camera if it is still idle when this timer fires.

        A timer that has already fired cannot be cancelled, so this re-checks
        under the lock that it is still the *current* timer and that no viewer
        arrived in the meantime - otherwise a fresh viewer's ``ensure_started``
        that raced this callback would be stopped out from under it.
        """

        with self._lock:
            if self._idle_timer is not timer or self._viewers > 0:
                return
            self._idle_timer = None
            self._stop_locked()

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
        """Signal the loop to stop and wait briefly for the thread to finish.

        Cancels any pending idle-stop and tears the camera down now. Safe to
        call whether the camera was opened eagerly (CLI) or lazily (API), and
        idempotent when nothing is running.
        """

        with self._lock:
            self._cancel_idle_timer_locked()
            self._stop_locked()

    def _stop_locked(self) -> None:
        """Signal the loop and join the thread; caller holds the lock."""

        self.stop_event.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=5.0)
            self._thread = None
