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

## Phase 7 - Matching, Attendance Logging, and Storage Scale Upgrade

Date: 2026-07-07

### Changed

- Added `EmployeeEmbeddingIndex`: a thread-safe, L2-normalized in-memory matrix of all active embeddings; matching is one vectorized matrix-vector product (tested at 1000 employees x 3 samples in well under 50 ms per match, actual ~sub-millisecond).
- Added `EmployeeMatcher` applying the documented SFace cosine threshold (0.363 similarity); empty-gallery and unknown faces return explicit non-matches.
- Added `AttendanceService`: clock-in/out toggling from last event, per-employee cooldown against duplicate logs, and hard gates on match + passed liveness.
- Storage scale upgrade (schema v2): WAL journal mode, busy timeout, indexes on `attendance_events(employee_id, occurred_at)` and `face_embeddings(employee_id)`; new `get_last_attendance_event`, `set_employee_active`, `count_employees` methods. Re-running `initialize_database` migrates v1 databases in place (indexes are `IF NOT EXISTS`).
- Added `tests/test_matching.py` (incl. 1000-employee scalability guard) and `tests/test_attendance_service.py`.

### Verified

- `python -m unittest discover -s tests` (68 tests, all green)

### Review

- Clean: unknown faces and failed liveness can never create attendance rows (tested).
- Clean: index refresh is lock-protected for the background-worker phase.
- Clean: inconsistent gallery dimensions (mixed models) fail loudly at index build, not silently at match time.

## Phase 8 - Multi-Frame Liveness

Date: 2026-07-07

### Changed

- Added `MicroMovementLivenessChecker` in `src/face_attendance/liveness/`: per-identity windows of landmark observations evaluated on two signals — motion presence (rejects static photos) and non-rigid deformation after removing translation/scale/rotation (rejects hand-waved photos and screens showing stills).
- Thresholds are normalized by inter-ocular distance, so they are resolution- and distance-independent; all parameters are constructor-configurable.
- Track hygiene: windows reset when a person leaves the frame (frame-id gap) and tracks are independent per identity.
- Added `tests/test_liveness.py` with synthetic sequences: live face passes; static photo, waved photo, and rotated photo fail with explicit reasons.

### Verified

- `python -m unittest discover -s tests` (77 tests, all green)

### Review

- Clean: liveness returns UNKNOWN (never PASSED) until a full evidence window exists, and the attendance service refuses to log on UNKNOWN.
- Documented limitation: a screen replaying a *video* of the employee produces non-rigid motion and is not caught; this is stated in code docs and will be in the README.
- Note: default thresholds are conservative estimates; the manual spoof-test checkpoint should confirm them on the real camera, and they are configurable if calibration is needed.

## Phase 9 - Non-Blocking Background Processing

Date: 2026-07-07

### Changed

- Added `src/face_attendance/pipeline/` with `LatestFrameSlot` and `RecognitionWorker`.
- `LatestFrameSlot` is a single-frame mailbox: a newer frame replaces an unconsumed one, so a backlog is impossible by construction; drops are counted for observability.
- `RecognitionWorker` runs detection -> embedding -> matching -> liveness -> attendance off the capture thread, delivering per-frame `RecognitionOutput`s via callback.
- Error policy: per-frame failures are reported and survived; a configurable number of consecutive failures stops the worker with an explicit `PipelineError`; unknown exceptions stop it immediately.
- Graceful shutdown via `stop()` (event + join with timeout, loud failure if the thread hangs).
- Added `tests/test_pipeline.py`: stale-frame dropping, multi-face frames, liveness gating, unknown faces, transient vs persistent errors, clean shutdown.

### Verified

- `python -m unittest discover -s tests` (87 tests, all green)

### Review

- Clean: worker never logs attendance for unmatched faces or without a passed liveness result (tested).
- Clean: one bad frame cannot kill the pipeline; a broken pipeline cannot fail silently.
- Clean: capture loop and recognition are fully decoupled; display smoothness no longer depends on model latency.

## Phase 10 - Configuration and End-to-End App Flow

Date: 2026-07-07

### Changed

- Added `AppSettings` (`src/face_attendance/config/`): every pipeline tunable in one validated Pydantic model with `FA_*` environment-variable overrides; invalid or unknown variables fail at startup naming the offending variable.
- Moved model-download logic into the package (`face_attendance/model_files.py`); `scripts/download_models.py` is now a thin wrapper and the CLI gained `download-models`.
- Added the app layer (`src/face_attendance/app/`): `build_components` factory, `run_enrollment` (frame-gapped quality sampling with operator feedback), `run_attendance` (capture loop + background worker + optional overlay display + deduplicated operator messages + session stats), and report/roster printers.
- Added `face_attendance/cli.py` with subcommands `init-db`, `download-models`, `enroll`, `attend`, `report`, `employees list|deactivate|activate`; registered the `face-attendance` console script; known errors map to clear messages and exit codes.
- `list_attendance_events` gained an indexed `limit` mode for reports on large tables.
- Added `tests/test_config.py` and `tests/test_app.py` (end-to-end enrollment and attendance with fakes, CLI dispatch tests).

### Verified

- `python -m unittest discover -s tests` (102 tests, all green)
- `python -m pip install -e .` and CLI help output

### Review

- Clean: flows accept injected components and frame sources, so end-to-end paths are tested without hardware.
- Clean: enrollment refreshes the match index immediately — a new employee is matchable without restarting attendance mode.
- Fixed during review: repeated `main()` calls no longer leak logging file handles (`force=True`).

## Phase 11 - Hardening and Documentation

Date: 2026-07-07

### Changed

- Rewrote `README.md` for production use: architecture diagram, setup, usage, configuration table, matching-threshold rationale, honest liveness limitations (video-replay gap), concurrency/backlog strategy, 1000-employee scalability design, and security/privacy notes.
- Updated `DIRECTORY_MAP.md` to cover every module and test added in phases 4-10.
- Finalized `docs/dependency-strategy.md`: core deps are pydantic + numpy + opencv-python; recognition-library extras removed with rationale.
- Marked phases 4-11 complete in `docs/project-plan.md`.
- CI now tests on Python 3.10 and 3.13.
- Added `docs/demo-checklist.md` (Phase 12 artifact, written here): rehearsal script for recognition, logging, multi-face, unknown rejection, spoof tests, resilience, and scale talking points.

### Verified

- `python -m unittest discover -s tests` (102 tests, all green)
- Console script `face-attendance --help` works after editable install.

### Review

- Independent code-review agent pass over phases 4-11 (findings addressed in Phase 12 entry below, if any).
- Network note: GitHub was unreachable during this session (confirmed by user); model download and `git push` remain pending. Pinned SHA256 hashes in `model_files.py` must be confirmed on first successful download — the script fails loudly with the actual hash if they differ.

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
