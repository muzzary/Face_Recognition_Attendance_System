import time
import unittest

from face_attendance.matching import (
    EmployeeEmbeddingIndex,
    EmployeeMatcher,
    MatchingError,
)
from fakes import make_embedding


def make_index(entries: list[tuple[str, list[float]]]) -> EmployeeEmbeddingIndex:
    return EmployeeEmbeddingIndex(
        [(employee_id, make_embedding(vector)) for employee_id, vector in entries]
    )


class EmbeddingIndexTests(unittest.TestCase):
    def test_best_match_returns_closest_employee(self) -> None:
        index = make_index(
            [
                ("EMP-001", [1.0, 0.0, 0.0]),
                ("EMP-002", [0.0, 1.0, 0.0]),
                ("EMP-003", [0.0, 0.0, 1.0]),
            ]
        )

        best = index.best_match(make_embedding([0.1, 0.95, 0.05]))

        assert best is not None
        self.assertEqual(best[0], "EMP-002")
        self.assertGreater(best[1], 0.9)

    def test_empty_index_returns_none(self) -> None:
        index = make_index([])

        self.assertIsNone(index.best_match(make_embedding([1.0, 0.0])))

    def test_multiple_embeddings_per_employee_use_best_sample(self) -> None:
        index = make_index(
            [
                ("EMP-001", [1.0, 0.0]),
                ("EMP-001", [0.7, 0.7]),
                ("EMP-002", [0.0, 1.0]),
            ]
        )

        best = index.best_match(make_embedding([0.72, 0.69]))

        assert best is not None
        self.assertEqual(best[0], "EMP-001")

    def test_dimension_mismatch_raises(self) -> None:
        index = make_index([("EMP-001", [1.0, 0.0, 0.0])])

        with self.assertRaises(MatchingError):
            index.best_match(make_embedding([1.0, 0.0]))

    def test_inconsistent_gallery_dimensions_raise(self) -> None:
        with self.assertRaises(MatchingError):
            make_index([("EMP-001", [1.0, 0.0]), ("EMP-002", [1.0, 0.0, 0.0])])

    def test_zero_probe_raises(self) -> None:
        index = make_index([("EMP-001", [1.0, 0.0])])

        with self.assertRaises(MatchingError):
            index.best_match(make_embedding([0.0, 0.0]))

    def test_thousand_employees_match_quickly(self) -> None:
        # Scalability guard: 1000 employees x 3 samples of 128-d vectors.
        entries = []
        for employee in range(1000):
            for sample in range(3):
                vector = [0.001] * 128
                vector[employee % 128] = 1.0
                vector[(employee * 7 + sample) % 128] += 0.05
                entries.append((f"EMP-{employee:04d}", vector))
        index = make_index(entries)
        probe_vector = [0.001] * 128
        probe_vector[500 % 128] = 1.0
        probe = make_embedding(probe_vector)

        started = time.perf_counter()
        for _ in range(50):
            index.best_match(probe)
        elapsed_per_match = (time.perf_counter() - started) / 50

        self.assertEqual(index.size, 3000)
        self.assertLess(elapsed_per_match, 0.05)


class EmployeeMatcherTests(unittest.TestCase):
    def test_similar_probe_matches_above_threshold(self) -> None:
        matcher = EmployeeMatcher(make_index([("EMP-001", [1.0, 0.0])]))

        result = matcher.match(make_embedding([0.98, 0.05]))

        self.assertTrue(result.is_match)
        self.assertEqual(result.employee_id, "EMP-001")
        self.assertLess(result.distance, result.threshold)
        self.assertGreater(result.confidence_score, 0.9)

    def test_dissimilar_probe_does_not_match(self) -> None:
        matcher = EmployeeMatcher(make_index([("EMP-001", [1.0, 0.0])]))

        result = matcher.match(make_embedding([0.0, 1.0]))

        self.assertFalse(result.is_match)
        self.assertIsNone(result.employee_id)
        self.assertGreaterEqual(result.distance, result.threshold)

    def test_empty_gallery_is_explicit_non_match(self) -> None:
        matcher = EmployeeMatcher(make_index([]))

        result = matcher.match(make_embedding([1.0, 0.0]))

        self.assertFalse(result.is_match)
        self.assertEqual(result.confidence_score, 0.0)

    def test_invalid_threshold_rejected(self) -> None:
        with self.assertRaises(ValueError):
            EmployeeMatcher(make_index([]), similarity_threshold=1.0)


if __name__ == "__main__":
    unittest.main()
