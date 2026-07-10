"""Hardware-free tests for the MJPEG streaming proof (scripts/stream_preview.py).

These prove the two properties the Phase 1 acceptance test cares about, without
a real webcam or HTTP sockets:
- the JPEG holder is latest-wins and non-blocking (a slow consumer never causes
  a backlog and always sees the newest frame);
- driving the real non-blocking capture loop (``run_attendance``) through the
  streamer emits a fresh JPEG per frame while a deliberately slow consumer never
  stalls the producer.
"""

from __future__ import annotations

import sys
import threading
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

from face_attendance.app import draw_overlay, run_attendance
from fakes import RepeatingDetector, RepeatingEmbedder, make_frame
from test_app import build_fake_components, open_source

# scripts/ is not an installed package; add it to the path like tests do for fakes.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import stream_preview  # noqa: E402


class LatestJpegFrameTests(unittest.TestCase):
    def test_get_after_returns_newest_skipping_stale(self) -> None:
        holder = stream_preview.LatestJpegFrame()
        holder.put(b"a")
        holder.put(b"b")
        holder.put(b"c")

        # A consumer that missed a and b jumps straight to the newest frame.
        self.assertEqual(holder.get_after(0, timeout=0.01), (b"c", 3))

    def test_get_after_times_out_when_nothing_newer(self) -> None:
        holder = stream_preview.LatestJpegFrame()
        holder.put(b"a")

        self.assertIsNone(holder.get_after(1, timeout=0.01))

    def test_get_after_wakes_on_put_from_other_thread(self) -> None:
        holder = stream_preview.LatestJpegFrame()

        def delayed_put() -> None:
            time.sleep(0.05)
            holder.put(b"x")

        threading.Thread(target=delayed_put, daemon=True).start()

        self.assertEqual(holder.get_after(0, timeout=1.0), (b"x", 1))


class FramingTests(unittest.TestCase):
    def test_mjpeg_chunk_has_boundary_headers_and_payload(self) -> None:
        chunk = stream_preview.mjpeg_chunk(b"\xff\xd8jpeg\xff\xd9")

        self.assertTrue(chunk.startswith(b"--faframe\r\n"))
        self.assertIn(b"Content-Type: image/jpeg\r\n", chunk)
        self.assertIn(b"Content-Length: 8\r\n\r\n", chunk)
        self.assertTrue(chunk.endswith(b"\xff\xd8jpeg\xff\xd9\r\n"))

    def test_encode_jpeg_produces_jpeg_magic_bytes(self) -> None:
        image = np.full((48, 64, 3), 90, dtype=np.uint8)

        jpeg = stream_preview.encode_jpeg(image)

        self.assertTrue(jpeg.startswith(b"\xff\xd8"))  # SOI
        self.assertTrue(jpeg.endswith(b"\xff\xd9"))  # EOI


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

            holder = stream_preview.LatestJpegFrame()
            stop = threading.Event()
            collected: list[tuple[int, bytes]] = []

            def slow_consumer() -> None:
                last = 0
                while not stop.is_set():
                    result = holder.get_after(last, timeout=0.1)
                    if result is None:
                        continue
                    jpeg, last = result
                    collected.append((last, jpeg))
                    time.sleep(0.02)  # a deliberately slow HTTP client

            consumer = threading.Thread(target=slow_consumer, daemon=True)
            consumer.start()

            def on_frame(frame, output) -> None:
                holder.put(stream_preview.encode_jpeg(draw_overlay(frame, output)))

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
            # produced, and the versions it did see strictly increase (frames
            # were dropped, never replayed).
            versions = [version for version, _ in collected]
            self.assertTrue(collected)
            self.assertLess(len(collected), frame_count)
            self.assertEqual(versions, sorted(set(versions)))
            # At least one gap > 1 proves latest-wins skipping of stale frames.
            self.assertTrue(
                any(b - a > 1 for a, b in zip(versions, versions[1:])),
                "slow consumer should skip intermediate frames (latest-wins)",
            )
            for _, jpeg in collected:
                self.assertTrue(jpeg.startswith(b"\xff\xd8"))


if __name__ == "__main__":
    unittest.main()
