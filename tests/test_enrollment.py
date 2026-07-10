import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from face_attendance.embeddings import EnrollmentError, EnrollmentService
from face_attendance.embeddings.sface import _face_to_yunet_row
from face_attendance.storage import AttendanceStorage, initialize_database
from fakes import (
    FakeDetector,
    FakeEmbedder,
    make_detected_face,
    make_embedding,
    make_frame,
)


def make_storage(temp_dir: str) -> AttendanceStorage:
    database_path = Path(temp_dir) / "attendance.db"
    initialize_database(database_path)
    return AttendanceStorage(database_path)


def make_service(
    storage: AttendanceStorage,
    detector: FakeDetector | None = None,
    embedder: FakeEmbedder | None = None,
    required_samples: int = 2,
) -> EnrollmentService:
    return EnrollmentService(
        detector=detector if detector is not None else FakeDetector([]),
        embedder=embedder if embedder is not None else FakeEmbedder([]),
        storage=storage,
        required_samples=required_samples,
    )


class CaptureSampleTests(unittest.TestCase):
    def test_no_face_raises(self) -> None:
        with TemporaryDirectory() as temp_dir:
            service = make_service(make_storage(temp_dir), detector=FakeDetector([[]]))

            with self.assertRaises(EnrollmentError) as ctx:
                service.capture_sample(make_frame())
            self.assertIn("no face", str(ctx.exception))

    def test_multiple_faces_raise(self) -> None:
        with TemporaryDirectory() as temp_dir:
            faces = [make_detected_face(), make_detected_face(x=150)]
            service = make_service(make_storage(temp_dir), detector=FakeDetector([faces]))

            with self.assertRaises(EnrollmentError) as ctx:
                service.capture_sample(make_frame())
            self.assertIn("exactly one", str(ctx.exception))

    def test_low_confidence_face_rejected(self) -> None:
        with TemporaryDirectory() as temp_dir:
            face = make_detected_face(confidence=0.5)
            service = make_service(make_storage(temp_dir), detector=FakeDetector([[face]]))

            with self.assertRaises(EnrollmentError) as ctx:
                service.capture_sample(make_frame())
            self.assertIn("confidence", str(ctx.exception))

    def test_small_face_rejected(self) -> None:
        with TemporaryDirectory() as temp_dir:
            face = make_detected_face(width=40, height=40)
            service = make_service(make_storage(temp_dir), detector=FakeDetector([[face]]))

            with self.assertRaises(EnrollmentError) as ctx:
                service.capture_sample(make_frame())
            self.assertIn("too small", str(ctx.exception))

    def test_good_face_returns_embedding(self) -> None:
        with TemporaryDirectory() as temp_dir:
            embedding = make_embedding()
            service = make_service(
                make_storage(temp_dir),
                detector=FakeDetector([[make_detected_face()]]),
                embedder=FakeEmbedder([embedding]),
            )

            self.assertEqual(service.capture_sample(make_frame()), embedding)


class EnrollTests(unittest.TestCase):
    def test_enroll_persists_employee_and_embeddings(self) -> None:
        with TemporaryDirectory() as temp_dir:
            storage = make_storage(temp_dir)
            service = make_service(storage)
            samples = [make_embedding([1.0, 0.1, 0.0]), make_embedding([1.0, 0.0, 0.1])]

            employee = service.enroll("EMP-001", "Ada Lovelace", samples)

            self.assertEqual(storage.get_employee("default", "EMP-001"), employee)
            self.assertEqual(
                storage.list_embeddings_for_employee("default", "EMP-001"), samples
            )

    def test_too_few_samples_rejected(self) -> None:
        with TemporaryDirectory() as temp_dir:
            service = make_service(make_storage(temp_dir), required_samples=3)

            with self.assertRaises(EnrollmentError) as ctx:
                service.enroll("EMP-001", "Ada", [make_embedding()])
            self.assertIn("need 3 samples", str(ctx.exception))

    def test_inconsistent_samples_rejected(self) -> None:
        with TemporaryDirectory() as temp_dir:
            service = make_service(make_storage(temp_dir))
            # Orthogonal vectors: similarity 0.0, far below the 0.4 floor.
            samples = [make_embedding([1.0, 0.0]), make_embedding([0.0, 1.0])]

            with self.assertRaises(EnrollmentError) as ctx:
                service.enroll("EMP-001", "Ada", samples)
            self.assertIn("inconsistent", str(ctx.exception))

    def test_duplicate_employee_rejected(self) -> None:
        with TemporaryDirectory() as temp_dir:
            storage = make_storage(temp_dir)
            service = make_service(storage)
            samples = [make_embedding(), make_embedding()]
            service.enroll("EMP-001", "Ada", samples)

            with self.assertRaises(EnrollmentError) as ctx:
                service.enroll("EMP-001", "Ada", samples)
            self.assertIn("already enrolled", str(ctx.exception))

    def test_no_raw_image_data_reaches_storage(self) -> None:
        with TemporaryDirectory() as temp_dir:
            storage = make_storage(temp_dir)
            service = make_service(storage)
            service.enroll("EMP-001", "Ada", [make_embedding(), make_embedding()])

            stored = storage.list_embeddings_for_employee("default", "EMP-001")
            for embedding in stored:
                self.assertTrue(all(isinstance(v, float) for v in embedding.vector))


class YuNetRowRoundTripTests(unittest.TestCase):
    def test_contract_rebuilds_fifteen_value_row(self) -> None:
        face = make_detected_face()

        row = _face_to_yunet_row(face)

        self.assertEqual(row.shape, (15,))
        self.assertEqual(row[0], face.bounding_box.x)
        self.assertAlmostEqual(float(row[14]), face.detection_confidence, places=5)
        assert face.landmarks is not None
        self.assertAlmostEqual(float(row[4]), face.landmarks.right_eye.x, places=5)
        self.assertAlmostEqual(float(row[13]), face.landmarks.mouth_left.y, places=5)


if __name__ == "__main__":
    unittest.main()
