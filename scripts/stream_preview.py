"""Standalone MJPEG proof: stream annotated recognition frames over HTTP.

Phase 1 of the web-product arc, and a deliberately small proof rather than the
final architecture. The reusable streaming primitives now live in
``face_attendance.api.streaming`` (shared with the authenticated Phase 7 API
route); this script is a thin stdlib-only CLI wrapper around them - no web
framework, no auth - that serves the shared ``LatestJpegFrame`` over a raw
``ThreadingHTTPServer`` at ``/stream``.

The core guarantee is preserved end to end: a slow HTTP client can never back up
the recognition worker (stale camera frames are dropped by the pipeline, and the
HTTP output uses the same latest-frame-wins ``LatestJpegFrame`` discipline).

Run:
    python scripts/stream_preview.py            # then open http://127.0.0.1:8000/
Stop with Ctrl+C.
"""

from __future__ import annotations

import argparse
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from face_attendance.api.streaming import (
    BOUNDARY,
    CameraStreamer,
    LatestJpegFrame,
    mjpeg_chunk,
)
from face_attendance.config import AppSettings

logger = logging.getLogger(__name__)

INDEX_HTML = (
    b"<!doctype html><title>Face Attendance stream</title>"
    b"<body style='margin:0;background:#111'>"
    b"<img src='/stream' style='width:100%;height:auto'>"
    b"</body>"
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

    settings = AppSettings.from_env()
    streamer = CameraStreamer(settings, camera_index=args.camera_index)
    streamer.start()  # opens the camera; fails loud if models/camera are missing

    server = StreamServer(
        (args.host, args.port), streamer.jpeg_frame, streamer.stop_event
    )
    print(
        f"MJPEG stream live at http://{args.host}:{args.port}/ "
        f"(raw stream at /stream). Press Ctrl+C to stop."
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\ninterrupted")
    finally:
        streamer.stop()
        server.shutdown()
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
