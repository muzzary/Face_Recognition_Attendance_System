from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class RepositoryStructureTests(unittest.TestCase):
    def test_required_documentation_exists(self) -> None:
        required_files = [
            "AGENTS.md",
            "DIRECTORY_MAP.md",
            "MISSION.md",
            "RESOURCES.md",
            "NOTES.md",
            "pyproject.toml",
            "README.md",
            "docs/dependency-strategy.md",
            "docs/project-plan.md",
            "docs/phase-log.md",
            "lessons/0001-python-project-anatomy.html",
            "lessons/0002-boundary-models.html",
            "reference/python-project-setup.html",
            "reference/pydantic-boundary-models.html",
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
            "lessons",
            "reference",
            "learning-records",
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

    def test_agents_file_mentions_core_project_requirements(self) -> None:
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")

        required_terms = [
            "Python 3.10+",
            "numeric embeddings only",
            "multi-frame liveness detection",
            "bounded queue",
            "Pydantic models",
            "docs/project-plan.md",
            "MISSION.md",
        ]

        for term in required_terms:
            with self.subTest(term=term):
                self.assertIn(term, agents)

    def test_project_plan_covers_required_phases(self) -> None:
        plan = (ROOT / "docs/project-plan.md").read_text(encoding="utf-8")

        required_terms = [
            "Camera Capture",
            "Face Detection",
            "Embeddings and Enrollment",
            "Matching and Attendance Logging",
            "Multi-Frame Liveness",
            "Non-Blocking Background Processing",
            "Demo and Submission Polish",
        ]

        for term in required_terms:
            with self.subTest(term=term):
                self.assertIn(term, plan)

    def test_dependency_strategy_names_required_dependency_families(self) -> None:
        strategy = (ROOT / "docs/dependency-strategy.md").read_text(encoding="utf-8")
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")

        required_terms = [
            "OpenCV",
            "Pydantic",
            "face-recognition or embedding library",
            "validation",
            "vision",
            "recognition-face-recognition",
            "recognition-insightface",
        ]

        combined = f"{strategy}\n{pyproject}"
        for term in required_terms:
            with self.subTest(term=term):
                self.assertIn(term, combined)


if __name__ == "__main__":
    unittest.main()
