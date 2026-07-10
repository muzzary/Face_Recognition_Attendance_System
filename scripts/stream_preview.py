"""Standalone MJPEG proof: stream annotated recognition frames over HTTP.

Phase 1 of the web-product arc, and a deliberately small proof rather than the
final architecture. It reuses the existing non-blocking capture loop
(``run_attendance``) and the shared ``draw_overlay`` annotation, then serves the
latest annotated frame as an MJPEG ``multipart/x-mixed-replace`` stream using
only the standard library -- no web framework (that arrives in a later phase).

The core guarantee is preserved end to end: a slow HTTP client can never back up
the recognition worker. Camera frames still flow through the pipeline's
``LatestFrameSlot`` (stale frames dropped, not queued), and the HTTP output uses
the same latest-frame-wins discipline via ``LatestJpegFrame`` below.

Run:
    python scripts/stream_preview.py            # then open http://127.0.0.1:8000/
Stop with Ctrl+C.
"""

from __future__ import annotations

import argparse
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

logger = logging.getLogger(__name__)

# Multipart boundary marker separating JPEG parts in the stream.
BOUNDARY = "faframe"

INDEX_HTML = (
    b"<!doctype html><title>Face Attendance stream</title>"
    b"<body style='margin:0;background:#111'>"
    b"<img src='/stream' style='width:100%;height:auto'>"
    b"</body>"
)


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


class _StreamHandler(BaseHTTPRequestHandler):
    """Serves the index page and the MJPEG stream from the server's holder."""

    def do_GET(self) -> None:  # noqa: N802 - http.server API
        if self.path == "/stream":
            self._serve_stream()
        elif self.path in ("/", "/index.html"):
            self._serve_index()
        else:
            self.send_error(404, "not found")

    def _serve_index(self) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(INDEX_HTML)))
        self.end_headers()
        self.wfile.write(INDEX_HTML)

    def _serve_stream(self) -> None:
        self.send_response(200)
        self.send_header(
            "Content-Type", f"multipart/x-mixed-replace; boundary={BOUNDARY}"
        )
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        last_version = 0
        try:
            while not self.server.stop_event.is_set():
                result = self.server.jpeg_frame.get_after(last_version, timeout=1.0)
                if result is None:
                    continue
                jpeg, last_version = result
                self.wfile.write(mjpeg_chunk(jpeg))
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            # Client closed the tab. Drop this stream quietly -- each client
            # streams on its own thread from the shared holder, so one leaving
            # never affects the producer or other viewers.
            pass

    def log_message(self, *args) -> None:  # noqa: N802 - silence per-request noise
        pass


class StreamServer(ThreadingHTTPServer):
    """Threaded HTTP server holding the shared JPEG frame and a stop flag."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        address: tuple[str, int],
        jpeg_frame: LatestJpegFrame,
        stop_event: threading.Event,
    ) -> None:
        super().__init__(address, _StreamHandler)
        self.jpeg_frame = jpeg_frame
        self.stop_event = stop_event


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="stream_preview",
        description="Stream annotated recognition frames as MJPEG over HTTP.",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--camera-index", type=int, default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )

    # Imported here so the testable streaming primitives above stay free of the
    # camera/CLI import chain (the unit tests never construct real hardware).
    from face_attendance.app import build_components, draw_overlay, run_attendance
    from face_attendance.cli import _make_camera, _require_models
    from face_attendance.config import AppSettings

    settings = AppSettings.from_env()
    _require_models(settings)
    components = build_components(settings)

    jpeg_frame = LatestJpegFrame()
    stop_event = threading.Event()
    server = StreamServer((args.host, args.port), jpeg_frame, stop_event)
    server_thread = threading.Thread(
        target=server.serve_forever, name="mjpeg-http", daemon=True
    )
    server_thread.start()
    print(
        f"MJPEG stream live at http://{args.host}:{args.port}/ "
        f"(raw stream at /stream). Press Ctrl+C to stop."
    )

    def on_frame(frame, output) -> None:
        # Encode on the capture thread -- the same place the cv2 preview draws.
        # The holder is latest-wins, so this never blocks on HTTP clients and
        # the recognition worker (a separate thread) is never touched here.
        jpeg_frame.put(encode_jpeg(draw_overlay(frame, output)))

    camera = _make_camera(settings, args.camera_index)
    try:
        run_attendance(components, camera, display=False, on_frame=on_frame)
    except KeyboardInterrupt:
        print("\ninterrupted")
    finally:
        stop_event.set()
        server.shutdown()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
