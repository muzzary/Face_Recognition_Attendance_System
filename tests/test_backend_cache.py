import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from face_attendance.capture import open_camera_remembering_backend
from face_attendance.capture.backend_cache import (
    load_cached_backend,
    store_cached_backend,
)
from fakes import FakeVideoCapture, make_image


class CacheFileTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        with TemporaryDirectory() as temp_dir:
            cache = Path(temp_dir) / "camera_backend.json"

            store_cached_backend(cache, 0, "dshow")

            self.assertEqual(load_cached_backend(cache, 0), "dshow")
            self.assertIsNone(load_cached_backend(cache, 1))

    def test_missing_and_corrupt_files_return_none(self) -> None:
        with TemporaryDirectory() as temp_dir:
            cache = Path(temp_dir) / "camera_backend.json"
            self.assertIsNone(load_cached_backend(cache, 0))

            cache.write_text("{not json", encoding="utf-8")
            self.assertIsNone(load_cached_backend(cache, 0))

    def test_unknown_backend_values_are_ignored(self) -> None:
        with TemporaryDirectory() as temp_dir:
            cache = Path(temp_dir) / "camera_backend.json"
            cache.write_text(json.dumps({"0": "gstreamer"}), encoding="utf-8")

            self.assertIsNone(load_cached_backend(cache, 0))
            store_cached_backend(cache, 0, "auto")  # not cacheable
            self.assertIsNone(load_cached_backend(cache, 0))

    def test_store_creates_parent_directory(self) -> None:
        with TemporaryDirectory() as temp_dir:
            cache = Path(temp_dir) / "nested" / "camera_backend.json"

            store_cached_backend(cache, 2, "default")

            self.assertEqual(load_cached_backend(cache, 2), "default")


class OpenWithCacheTests(unittest.TestCase):
    """Camera opening via the cache, with cv2 mocked at the module boundary."""

    def open_with_backends(self, cache: Path, capture_for_flag):
        with patch("cv2.VideoCapture", side_effect=capture_for_flag), patch(
            "face_attendance.capture.camera.sys.platform", "win32"
        ), patch("face_attendance.capture.camera.time.sleep"):
            return open_camera_remembering_backend(0, "auto", cache)

    def test_first_open_probes_and_stores_working_backend(self) -> None:
        silent = FakeVideoCapture(opened=True, frames=[])
        working = FakeVideoCapture(opened=True, frames=[make_image()] * 20)

        with TemporaryDirectory() as temp_dir:
            cache = Path(temp_dir) / "camera_backend.json"
            camera = self.open_with_backends(
                cache, lambda index, flag=None: silent if flag is None else working
            )
            camera.close()

            self.assertEqual(camera.backend_used, "dshow")
            self.assertEqual(load_cached_backend(cache, 0), "dshow")

    def test_cached_backend_is_used_directly(self) -> None:
        working = FakeVideoCapture(opened=True, frames=[make_image()] * 20)
        calls: list[object] = []

        def factory(index, flag=None):
            calls.append(flag)
            return working

        with TemporaryDirectory() as temp_dir:
            cache = Path(temp_dir) / "camera_backend.json"
            store_cached_backend(cache, 0, "dshow")

            camera = self.open_with_backends(cache, factory)
            camera.close()

            # Exactly one attempt, straight to the cached backend (a flag,
            # not the flagless default).
            self.assertEqual(len(calls), 1)
            self.assertIsNotNone(calls[0])

    def test_stale_cache_reprobes_and_refreshes(self) -> None:
        # Cached backend no longer delivers; auto probe must run and the
        # cache must be rewritten with what works now.
        with TemporaryDirectory() as temp_dir:
            cache = Path(temp_dir) / "camera_backend.json"
            store_cached_backend(cache, 0, "msmf")

            working_default = FakeVideoCapture(opened=True, frames=[make_image()] * 20)

            def factory(index, flag=None):
                if flag is None:
                    return working_default
                return FakeVideoCapture(opened=False)  # msmf and dshow dead

            camera = self.open_with_backends(cache, factory)
            camera.close()

            self.assertEqual(camera.backend_used, "default")
            self.assertEqual(load_cached_backend(cache, 0), "default")

    def test_forced_backend_bypasses_cache(self) -> None:
        working = FakeVideoCapture(opened=True, frames=[make_image()] * 20)

        with TemporaryDirectory() as temp_dir:
            cache = Path(temp_dir) / "camera_backend.json"
            with patch("cv2.VideoCapture", return_value=working), patch(
                "face_attendance.capture.camera.time.sleep"
            ):
                camera = open_camera_remembering_backend(0, "dshow", cache)
            camera.close()

            self.assertFalse(cache.exists())


if __name__ == "__main__":
    unittest.main()
