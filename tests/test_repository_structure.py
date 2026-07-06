from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class RepositoryStructureTests(unittest.TestCase):
    def test_required_documentation_exists(self) -> None:
        required_files = [
            "AGENTS.md",
            "DIRECTORY_MAP.md",
            "README.md",
            "docs/phase-log.md",
        ]

        for relative_path in required_files:
            with self.subTest(path=relative_path):
                self.assertTrue((ROOT / relative_path).is_file())

    def test_expected_source_folders_exist(self) -> None:
        required_directories = [
            "src/face_attendance/capture",
            "src/face_attendance/detection",
            "src/face_attendance/embeddings",
            "src/face_attendance/matching",
            "src/face_attendance/liveness",
            "src/face_attendance/storage",
            "src/face_attendance/attendance_logging",
            "src/face_attendance/config",
        ]

        for relative_path in required_directories:
            with self.subTest(path=relative_path):
                self.assertTrue((ROOT / relative_path).is_dir())

    def test_gitignore_blocks_sensitive_runtime_files(self) -> None:
        gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")

        required_patterns = [".env", "data/*", "logs/", "recordings/"]
        for pattern in required_patterns:
            with self.subTest(pattern=pattern):
                self.assertIn(pattern, gitignore)


if __name__ == "__main__":
    unittest.main()
