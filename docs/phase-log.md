# Phase Log

## Phase 0 - Repository Root Setup

Date: 2026-07-06

### Changed

- Initialized project navigation docs with `AGENTS.md` and `DIRECTORY_MAP.md`.
- Added a practical starter `README.md`.
- Added `.gitignore` rules for Python caches, environments, secrets, runtime data, logs, and recordings.
- Added modular source folders based on the Khizex face-recognition attendance specification.
- Added lightweight repository structure tests.
- Added a simple GitHub Actions workflow for push and pull request checks.

### Verified

- `python -m unittest discover -s tests`
- `git status --short --branch`

### Review

- Clean: no secrets, raw biometric files, generated recordings, or runtime databases were added.
- Clean: no third-party dependencies were introduced.

## Phase 0 Follow-up - Agent Requirements Alignment

Date: 2026-07-06

### Changed

- Added the core Khizex project requirements to `AGENTS.md`.
- Added simple implementation instructions for storage, liveness, concurrency, validation, and biometric data safety.

### Verified

- `python -m unittest discover -s tests`
- `git diff --check`

### Review

- Clean: documentation-only update.
- Clean: no dependencies, secrets, runtime data, or biometric files were added.

## Phase 0 Follow-up - Project Plan and Teaching Workspace

Date: 2026-07-06

### Changed

- Added a phase-by-phase build and learning roadmap in `docs/project-plan.md`.
- Added teaching workspace files: `MISSION.md`, `RESOURCES.md`, `NOTES.md`, `lessons/`, `reference/`, and `learning-records/`.
- Updated `AGENTS.md`, `DIRECTORY_MAP.md`, and `README.md` to point future work at the plan and teaching workflow.

### Verified

- `python -m unittest discover -s tests`
- `git diff --check`

### Review

- Clean: planning/documentation-only update.
- Clean: no dependencies, secrets, runtime data, or biometric files were added.

## Phase 1 - Tooling and Dependency Decision

Date: 2026-07-06

### Changed

- Added `pyproject.toml` with Python 3.10+ metadata, setuptools build backend, `src` package discovery, and no application dependencies.
- Declared PDF-required dependency families as optional extras: validation, vision, and recognition choices.
- Added `docs/dependency-strategy.md` to explain when each dependency should be installed.
- Updated CI to install the package in editable mode before running tests.
- Added package import/version test.
- Added Phase 1 teaching lesson and Python project setup reference.
- Updated README setup instructions and directory map.

### Verified

- `python -m pip install -e .`
- `python -m unittest discover -s tests`
- `git diff --check`

### Review

- Clean: default install remains dependency-light.
- Clean: PDF-required dependency families are recorded as optional extras and explained in docs.
- Clean: no secrets, runtime data, or biometric files were added.

## Phase 2 - Core Data Contracts

Date: 2026-07-06

### Changed

- Added Pydantic as a core runtime dependency.
- Added immutable boundary models in `src/face_attendance/contracts.py`.
- Added contract tests for valid payloads, malformed payloads, extra fields, timestamp awareness, embedding dimensions, match consistency, and failed liveness reasons.
- Added Phase 2 lesson and Pydantic boundary-model reference.
- Updated README, dependency strategy, directory map, project plan, and phase log.

### Verified

- `python -m pip install -e .`
- `python -m unittest discover -s tests`
- `python -c "from face_attendance.contracts import FaceEmbedding; print(FaceEmbedding(vector=[0.1], dimensions=1, model_name='demo').model_name)"`
- `git diff --check`

### Review

- Clean: boundary models reject extra fields and malformed data.
- Clean: attendance and employee payloads store metadata and numeric values only, not raw images.
- Clean: no secrets, runtime data, camera captures, or biometric files were added.
