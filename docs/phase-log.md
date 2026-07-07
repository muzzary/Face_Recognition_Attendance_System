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

## Phase 4 - Camera Capture

Date: 2026-07-07

### Changed

- Added `src/face_attendance/capture/` with `OpenCvCamera`, the `FrameSource` protocol, an in-memory `Frame` container, and `CaptureError`.
- Promoted `numpy` and `opencv-python` to core dependencies; removed the unused recognition-library extras because detection/embeddings will use YuNet + SFace, which ship inside `opencv-python`.
- Updated CI to install `libgl1`/`libglib2.0-0` so OpenCV imports on Ubuntu runners.
- Added `tests/fakes.py` (fake video capture and frame source reused across later phases) and `tests/test_capture.py`.

### Verified

- `python -m pip install -e .`
- `python -m unittest discover -s tests` (37 tests, all green)

### Review

- Clean: raw frames live only in memory; nothing writes image bytes to disk.
- Clean: camera open/read/corrupt/disconnect failures raise `CaptureError` with actionable messages.
- Clean: capture factory is injectable, so all error paths are unit-tested without hardware.

## Phase 5 - Face Detection

Date: 2026-07-07

### Changed

- Added `Point` and `FaceLandmarks` contracts and an optional `landmarks` field on `DetectedFace` (needed by SFace alignment and multi-frame liveness).
- Added `src/face_attendance/detection/` with the `FaceDetector` protocol, `DetectionError`, and a `YuNetDetector` adapter (`cv2.FaceDetectorYN`).
- YuNet output rows are converted to validated contracts: boxes clamped to the frame, degenerate boxes dropped, scores clamped to [0, 1].
- Added `scripts/download_models.py` (stdlib-only, SHA256-pinned, atomic writes) for the YuNet and SFace ONNX models; `models/` is gitignored.
- Added `tests/test_detection.py`; the real-model smoke test auto-skips when models are absent, so CI stays green without downloads.

### Verified

- `python -m unittest discover -s tests`
- Model download pending: GitHub was unreachable from this machine during the phase; the script verifies hashes on first successful run and fails loudly with the actual hash on mismatch.

### Review

- Clean: cv2 types never cross the detection boundary; the pipeline sees Pydantic contracts only.
- Clean: missing model file produces a clear "run scripts/download_models.py" error instead of a cv2 stack trace.
- Note: pinned SHA256 values must be confirmed on the first successful download (mismatch fails loudly and prints the actual hash).

## Phase 6 - Embeddings and Enrollment

Date: 2026-07-07

### Changed

- Added `src/face_attendance/embeddings/` with the `EmbeddingExtractor` protocol, `EmbeddingError`, and an `SFaceEmbedder` adapter (`cv2.FaceRecognizerSF`, 128-d vectors).
- Added `EnrollmentService` with quality gates: exactly one face in frame, minimum detection confidence, minimum face size, minimum sample count, and pairwise-consistency checks across samples.
- Added `matching/similarity.py` with defensive cosine-similarity helpers (zero-norm and dimension-mismatch failures are explicit).
- Extended `tests/fakes.py` with fake detector/embedder and contract factories; added `tests/test_enrollment.py`.

### Verified

- `python -m unittest discover -s tests` (48 tests, all green)

### Review

- Clean: aligned face crops are discarded inside the embedder; only numeric vectors leave the module.
- Clean: enrollment consistency gate rejects sample sets contaminated by a second person.
- Clean: duplicate enrollment fails with a clear message instead of a database error.

## Phase 3 - Storage Foundation

Date: 2026-07-06

### Changed

- Added SQLite schema initialization and a storage repository.
- Added employees, face embeddings, and attendance events tables.
- Added storage tests for round trips, foreign key enforcement, parent directory creation, and schema safety.
- Added Phase 3 lesson and SQLite storage reference.
- Updated README, directory map, project plan, and phase log.

### Verified

- `python -m unittest tests.test_storage`
- `python -m unittest discover -s tests`
- Storage schema smoke check with `AttendanceStorage.list_table_columns()`
- `git diff --check`

### Review

- Clean: schema stores employee metadata, numeric embedding vectors, and attendance event metadata only.
- Clean: no raw image, photo, frame path, raw byte, or capture columns exist.
- Clean: foreign keys are enabled on every connection and tested against orphan embeddings/events.
- Clean: storage errors are wrapped in `StorageError` with context.
