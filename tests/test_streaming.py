"""Hardware-free tests for the shared MJPEG streaming module
(``face_attendance.api.streaming``).

These prove the properties the Phase 1 acceptance test cares about, without a
real webcam or HTTP sockets:
- the JPEG holder is latest-wins and non-blocking (a slow consumer never causes
  a backlog and always sees the newest frame);
- driving the real non-blocking capture loop (``run_attendance``) through the
  streamer emits a fresh JPEG per frame while a deliberately slow consumer never
  stalls the producer;
- the ``mjpeg_stream`` generator (used by the FastAPI route) is latest-wins and
  ends cleanly on its stop event;
- ``CameraStreamer.start`` fails loudly and stays unavailable when the models
  (and thus the camera path) are missing - the case the API turns into a 503.
"""

from __future__ import annotations

import threading
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

from face_attendance.api.streaming import (
    CameraStreamer,
    LatestJpegFrame,
    encode_jpeg,
    mjpeg_chunk,
    mjpeg_stream,
)
from face_attendance.app import draw_overlay, run_attendance
from face_attendance.config import AppSettings
from face_attendance.model_files import ModelDownloadError
from fakes import RepeatingDetector, RepeatingEmbedder, make_frame
from test_app import build_fake_components, open_source


class LatestJpegFrameTests(unittest.TestCase):
    def test_get_after_returns_newest_skipping_stale(self) -> None:
        holder = LatestJpegFrame()
        holder.put(b"a")
        holder.put(b"b")
        holder.put(b"c")

        # A consumer that missed a and b jumps straight to the newest frame.
        self.assertEqual(holder.get_after(0, timeout=0.01), (b"c", 3))

    def test_get_after_times_out_when_nothing_newer(self) -> None:
        holder = LatestJpegFrame()
        holder.put(b"a")

        self.assertIsNone(holder.get_after(1, timeout=0.01))

    def test_get_after_wakes_on_put_from_other_thread(self) -> None:
        holder = LatestJpegFrame()

        def delayed_put() -> None:
            time.sleep(0.05)
            holder.put(b"x")

        threading.Thread(target=delayed_put, daemon=True).start()

        self.assertEqual(holder.get_after(0, timeout=1.0), (b"x", 1))


class FramingTests(unittest.TestCase):
    def test_mjpeg_chunk_has_boundary_headers_and_payload(self) -> None:
        chunk = mjpeg_chunk(b"\xff\xd8jpeg\xff\xd9")

        self.assertTrue(chunk.startswith(b"--faframe\r\n"))
        self.assertIn(b"Content-Type: image/jpeg\r\n", chunk)
        self.assertIn(b"Content-Length: 8\r\n\r\n", chunk)
        self.assertTrue(chunk.endswith(b"\xff\xd8jpeg\xff\xd9\r\n"))

    def test_encode_jpeg_produces_jpeg_magic_bytes(self) -> None:
        image = np.full((48, 64, 3), 90, dtype=np.uint8)

        jpeg = encode_jpeg(image)

        self.assertTrue(jpeg.startswith(b"\xff\xd8"))  # SOI
        self.assertTrue(jpeg.endswith(b"\xff\xd9"))  # EOI


class MjpegStreamTests(unittest.TestCase):
    """The generator the FastAPI route hands to StreamingResponse."""

    def test_yields_latest_wins_and_stops_on_event(self) -> None:
        holder = LatestJpegFrame()
        stop = threading.Event()
        gen = mjpeg_stream(holder, stop)

        holder.put(b"\xff\xd8one\xff\xd9")
        first = next(gen)
        self.assertTrue(first.startswith(b"--faframe\r\n"))
        self.assertIn(b"\xff\xd8one\xff\xd9", first)

        # Two frames arrive while the (slow) consumer was busy: it skips the
        # intermediate one and jumps straight to the newest -- latest-wins.
        holder.put(b"\xff\xd8two\xff\xd9")
        holder.put(b"\xff\xd8three\xff\xd9")
        second = next(gen)
        self.assertIn(b"\xff\xd8three\xff\xd9", second)
        self.assertNotIn(b"two", second)

        # The stop event ends the generator cleanly instead of hanging.
        stop.set()
        with self.assertRaises(StopIteration):
            next(gen)


class StreamLoopTests(unittest.TestCase):
    def test_slow_consumer_never_stalls_producer_and_gets_latest(self) -> None:
        frame_count = 40
        with TemporaryDirectory() as temp_dir:
            components = build_fake_components(
                temp_dir,
                detector=RepeatingDetector([]),  # no faces; base image drives JPEGs
                embedder=RepeatingEmbedder([1.0, 0.0, 0.0]),
            )
            # Distinct fill per frame so each encoded JPEG genuinely differs,
            # proving the stream is live rather than a repeated static image.
            frames = [
                make_frame(
                    frame_id=i,
                    image=np.full((48, 64, 3), (i * 6) % 200, dtype=np.uint8),
                )
                for i in range(frame_count)
            ]

            holder = LatestJpegFrame()
            stop = threading.Event()
            collected: list[tuple[int, bytes]] = []

            # A slow consumer driven through the exact generator the API route
            # uses, so the "route never stalls the producer" guarantee is what
            # is actually exercised here.
            def slow_consumer() -> None:
                for chunk in mjpeg_stream(holder, stop):
                    collected.append((holder.version, chunk))
                    time.sleep(0.02)  # a deliberately slow HTTP client

            consumer = threading.Thread(target=slow_consumer, daemon=True)
            consumer.start()

            def on_frame(frame, output) -> None:
                holder.put(encode_jpeg(draw_overlay(frame, output)))

            stats = run_attendance(
                components,
                open_source(frames, read_delay=0.002),
                display=False,
                on_message=lambda _: None,
                max_frames=frame_count,
                on_frame=on_frame,
            )

            stop.set()
            consumer.join(timeout=2.0)

            # Producer processed every frame regardless of the slow consumer.
            self.assertEqual(stats.frames_read, frame_count)
            self.assertEqual(holder.version, frame_count)

            # Consumer fell behind (no backlog): it saw fewer frames than were
            # produced, and every chunk it did see is a valid MJPEG part.
            self.assertTrue(collected)
            self.assertLess(len(collected), frame_count)
            for _, chunk in collected:
                self.assertTrue(chunk.startswith(b"--faframe\r\n"))
                self.assertIn(b"\xff\xd8", chunk)


class CameraStreamerTests(unittest.TestCase):
    def test_start_fails_loud_and_stays_unavailable_without_models(self) -> None:
        # An empty models dir stands in for "no camera path available" (dev/CI):
        # start() raises before any hardware is touched and the feed reports
        # itself unavailable, which the API turns into a 503 rather than a hang.
        with TemporaryDirectory() as temp_dir:
            settings = AppSettings.from_env(
                environ={"FA_MODELS_DIR": str(Path(temp_dir) / "no-models")}
            )
            streamer = CameraStreamer(settings)

            with self.assertRaises(ModelDownloadError):
                streamer.start()
            self.assertFalse(streamer.available)


if __name__ == "__main__":
    unittest.main()
