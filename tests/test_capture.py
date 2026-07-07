import unittest

import numpy as np

from face_attendance.capture import CaptureError, OpenCvCamera
from fakes import FakeVideoCapture, make_image


class OpenCvCameraTests(unittest.TestCase):
    def test_open_failure_raises_capture_error(self) -> None:
        camera = OpenCvCamera(capture_factory=lambda index: FakeVideoCapture(opened=False))

        with self.assertRaises(CaptureError):
            camera.open()

    def test_factory_exception_is_wrapped(self) -> None:
        def broken_factory(index: int) -> object:
            raise RuntimeError("no backend")

        camera = OpenCvCamera(capture_factory=broken_factory)

        with self.assertRaises(CaptureError):
            camera.open()

    def test_read_before_open_raises(self) -> None:
        camera = OpenCvCamera(capture_factory=lambda index: FakeVideoCapture())

        with self.assertRaises(CaptureError):
            camera.read()

    def test_read_returns_frame_with_metadata_and_incrementing_ids(self) -> None:
        images = [make_image(width=64, height=48), make_image(width=64, height=48)]
        fake = FakeVideoCapture(frames=list(images))
        camera = OpenCvCamera(camera_index=2, capture_factory=lambda index: fake)

        camera.open()
        first = camera.read()
        second = camera.read()
        camera.close()

        self.assertEqual(first.metadata.frame_id, 0)
        self.assertEqual(second.metadata.frame_id, 1)
        self.assertEqual(first.metadata.camera_id, "camera-2")
        self.assertEqual(first.metadata.width, 64)
        self.assertEqual(first.metadata.height, 48)
        self.assertIsNotNone(first.metadata.captured_at.tzinfo)
        self.assertTrue(np.array_equal(first.image, images[0]))

    def test_failed_read_raises_disconnect_error(self) -> None:
        fake = FakeVideoCapture(frames=[])
        camera = OpenCvCamera(capture_factory=lambda index: fake)
        camera.open()

        with self.assertRaises(CaptureError):
            camera.read()

    def test_corrupted_frame_raises(self) -> None:
        corrupted = np.zeros((0, 0, 3), dtype=np.uint8)
        fake = FakeVideoCapture(frames=[corrupted])
        camera = OpenCvCamera(capture_factory=lambda index: fake)
        camera.open()

        with self.assertRaises(CaptureError):
            camera.read()

    def test_driver_exception_during_read_is_wrapped(self) -> None:
        fake = FakeVideoCapture(read_raises=True)
        camera = OpenCvCamera(capture_factory=lambda index: fake)
        camera.open()

        with self.assertRaises(CaptureError):
            camera.read()

    def test_context_manager_opens_and_releases(self) -> None:
        fake = FakeVideoCapture(frames=[make_image()])
        with OpenCvCamera(capture_factory=lambda index: fake) as camera:
            camera.read()

        self.assertTrue(fake.released)

    def test_negative_camera_index_rejected(self) -> None:
        with self.assertRaises(ValueError):
            OpenCvCamera(camera_index=-1)


if __name__ == "__main__":
    unittest.main()
