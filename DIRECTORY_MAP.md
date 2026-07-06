# Directory Map

Last updated: 2026-07-06

## Root

- `.gitignore` - ignores Python caches, virtual environments, secrets, runtime logs, recordings, and local biometric data.
- `AGENTS.md` - project-specific working instructions and engineering standards.
- `DIRECTORY_MAP.md` - quick navigation map for every important folder and file.
- `README.md` - project overview, setup notes, and current build status.
- `.github/workflows/ci.yml` - lightweight CI that runs repository structure tests on push and pull request.

## Source

- `src/face_attendance/__init__.py` - package marker for the attendance system.
- `src/face_attendance/capture/` - camera and frame acquisition code.
- `src/face_attendance/detection/` - face detection code.
- `src/face_attendance/embeddings/` - facial embedding extraction code.
- `src/face_attendance/matching/` - employee matching and scoring code.
- `src/face_attendance/liveness/` - anti-spoofing and multi-frame liveness checks.
- `src/face_attendance/storage/` - database access, employee records, and attendance persistence.
- `src/face_attendance/attendance_logging/` - attendance event logging helpers. Named to avoid conflicting with Python's standard `logging` module.
- `src/face_attendance/config/` - application configuration loading and validation.

## Tests

- `tests/test_repository_structure.py` - starter safety tests for required docs and source folders.

## Docs

- `docs/phase-log.md` - phase-by-phase change log and verification notes.

## Local Runtime Folders

- `data/.gitkeep` - keeps the local data folder present while ignoring generated database/runtime data.
- `logs/` - ignored runtime logs created during local runs.
- `recordings/` - ignored local demo recordings.

