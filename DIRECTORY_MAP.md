# Directory Map

Last updated: 2026-07-06

## Root

- `.gitignore` - ignores Python caches, virtual environments, secrets, runtime logs, recordings, and local biometric data.
- `AGENTS.md` - project-specific working instructions and engineering standards.
- `DIRECTORY_MAP.md` - quick navigation map for every important folder and file.
- `MISSION.md` - teaching mission for learning the project while building it.
- `RESOURCES.md` - curated source list for learning and implementation decisions.
- `NOTES.md` - teaching and collaboration notes.
- `pyproject.toml` - Python packaging metadata, build backend, package discovery, and future tool configuration.
- `README.md` - project overview, setup notes, and current build status.
- `.github/workflows/ci.yml` - lightweight CI that runs repository structure tests on push and pull request.

## Source

- `src/face_attendance/__init__.py` - package marker for the attendance system.
- `src/face_attendance/contracts.py` - Pydantic data contracts for frame metadata, detections, embeddings, employees, matching, liveness, and attendance events.
- `src/face_attendance/capture/` - camera and frame acquisition code.
- `src/face_attendance/detection/` - face detection code.
- `src/face_attendance/embeddings/` - facial embedding extraction code.
- `src/face_attendance/matching/` - employee matching and scoring code.
- `src/face_attendance/liveness/` - anti-spoofing and multi-frame liveness checks.
- `src/face_attendance/storage/` - database access, employee records, and attendance persistence.
- `src/face_attendance/storage/__init__.py` - public storage exports.
- `src/face_attendance/storage/database.py` - SQLite schema initialization and attendance repository.
- `src/face_attendance/attendance_logging/` - attendance event logging helpers. Named to avoid conflicting with Python's standard `logging` module.
- `src/face_attendance/config/` - application configuration loading and validation.

## Tests

- `tests/test_repository_structure.py` - starter safety tests for required docs and source folders.
- `tests/test_package_import.py` - verifies the installable package can be imported.
- `tests/test_contracts.py` - verifies core Pydantic data contracts accept valid payloads and reject malformed ones.
- `tests/test_storage.py` - verifies SQLite schema creation, employee/embedding/event persistence, foreign keys, and no raw image columns.

## Docs

- `docs/dependency-strategy.md` - required dependency families, optional extras, and when each dependency should be installed.
- `docs/project-plan.md` - phase-by-phase build and learning roadmap.
- `docs/phase-log.md` - phase-by-phase change log and verification notes.

## Teaching Workspace

- `lessons/0001-python-project-anatomy.html` - Phase 1 lesson on project packaging structure.
- `lessons/0002-boundary-models.html` - Phase 2 lesson on Pydantic boundary validation.
- `lessons/0003-sqlite-storage-boundaries.html` - Phase 3 lesson on storage boundaries and secure schema design.
- `reference/python-project-setup.html` - quick reference for setup commands and file roles.
- `reference/pydantic-boundary-models.html` - quick reference for core contract models and validation rules.
- `reference/sqlite-storage.html` - quick reference for storage tables and repository methods.
- `lessons/` - short HTML lessons created before implementation phases.
- `reference/` - reusable quick-reference teaching documents.
- `learning-records/` - evidence-backed learning records created when understanding is demonstrated.

## Local Runtime Folders

- `data/.gitkeep` - keeps the local data folder present while ignoring generated database/runtime data.
- `logs/` - ignored runtime logs created during local runs.
- `recordings/` - ignored local demo recordings.
