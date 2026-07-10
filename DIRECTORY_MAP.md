# Directory Map

Last updated: 2026-07-10

## Root

- `.gitignore` - ignores Python caches, virtual environments, secrets, runtime logs, recordings, downloaded models, and local biometric data.
- `AGENTS.md` - project-specific working instructions and engineering standards.
- `DIRECTORY_MAP.md` - quick navigation map for every important folder and file.
- `MISSION.md` - teaching mission for learning the project while building it.
- `RESOURCES.md` - curated source list for learning and implementation decisions.
- `NOTES.md` - teaching and collaboration notes.
- `pyproject.toml` - packaging metadata, core dependencies (pydantic, numpy, opencv-python), and the `face-attendance` console script.
- `README.md` - setup, usage, threshold rationale, liveness limitations, concurrency design, scalability, and security notes.
- `.github/workflows/ci.yml` - CI running the full test suite on push and pull request.

## Source (`src/face_attendance/`)

- `__init__.py` - package marker.
- `contracts.py` - Pydantic data contracts: frames, boxes, landmarks, embeddings, employees, matches, liveness, attendance events (employee/embedding/attendance records carry a required `org_id` tenant tag).
- `model_files.py` - pinned ONNX model specs and hash-verified download logic (stdlib only).
- `cli.py` - `face-attendance` command-line interface (init-db, download-models, enroll, attend, report, employees).
- `capture/` - `OpenCvCamera`, `FrameSource` protocol, in-memory `Frame`, `CaptureError`.
- `detection/` - `FaceDetector` protocol, `DetectionError`, `YuNetDetector` adapter (cv2.FaceDetectorYN).
- `embeddings/` - `EmbeddingExtractor` protocol, `SFaceEmbedder` adapter (cv2.FaceRecognizerSF), `EnrollmentService` with quality gates.
- `matching/` - cosine similarity helpers, `EmployeeEmbeddingIndex` (vectorized in-memory gallery), `EmployeeMatcher` (threshold decisions).
- `liveness/` - `MicroMovementLivenessChecker`: multi-frame motion + non-rigidity anti-spoofing.
- `pipeline/` - `LatestFrameSlot` (stale-frame dropping) and `RecognitionWorker` (background recognition thread).
- `attendance_logging/` - `AttendanceService`: clock-in/out toggling, cooldown, liveness gating. Named to avoid clashing with stdlib `logging`.
- `storage/` - SQLite schema (WAL, indexes, org-scoped tables) and `AttendanceStorage` repository; `migrate_to_org_scoping` upgrades a pre-tenant v2 database to the org-scoped v3 schema in place.
- `config/` - `AppSettings`: validated runtime configuration with `FA_*` env overrides.
- `app/` - application flows: `factory.py` (component wiring), `enroll.py`, `attend.py`, `report.py`, `calibrate.py` (per-camera liveness threshold recommendation).

## Scripts

- `scripts/download_models.py` - thin CLI wrapper around `face_attendance.model_files`.
- `scripts/stream_preview.py` - stdlib-only MJPEG proof: reuses the pipeline (`build_components`/`run_attendance`) and `draw_overlay`, serving the latest annotated frame as a `multipart/x-mixed-replace` stream at `/stream` with latest-frame-wins output (no web framework).

## Tests

- `tests/fakes.py` - shared hardware-free fakes (camera, detector, embedder, liveness) and contract factories.
- `tests/test_repository_structure.py` - required docs and source folders exist.
- `tests/test_package_import.py` - installable package imports.
- `tests/test_contracts.py` - contract validation behavior.
- `tests/test_storage.py` - schema, round trips, foreign keys, no raw-image columns.
- `tests/test_org_scoping.py` - per-read-method tenant isolation, the v2->v3 migration (zero data loss, default-org tagging), and loud failures on missing/unknown org.
- `tests/test_capture.py` - camera open/read/corrupt/disconnect error paths.
- `tests/test_detection.py` - YuNet row conversion, clamping, model-missing errors.
- `tests/test_enrollment.py` - sample quality gates and enrollment persistence.
- `tests/test_matching.py` - index correctness, thresholds, 1000-employee latency guard.
- `tests/test_attendance_service.py` - clock-in/out toggling, cooldown, gating; storage upgrade methods.
- `tests/test_liveness.py` - synthetic live/static/waved/rotated sequences.
- `tests/test_pipeline.py` - backpressure, worker error policy, shutdown.
- `tests/test_config.py` - settings defaults, env overrides, validation errors.
- `tests/test_app.py` - end-to-end enrollment/attendance with fakes, CLI dispatch.
- `tests/test_calibrate.py` - liveness calibration sampling, recommendation formulas, report output.
- `tests/test_stream_preview.py` - MJPEG streamer: latest-wins/non-blocking JPEG holder, multipart framing, and the slow-consumer-never-stalls-producer guarantee over the real capture loop.

## Docs

- `docs/dependency-strategy.md` - dependency decisions and rationale.
- `docs/project-plan.md` - phase-by-phase build and learning roadmap.
- `docs/phase-log.md` - phase-by-phase change log and verification notes.
- `docs/demo-checklist.md` - demo rehearsal script covering recognition, logging, and spoof rejection.

## Teaching Workspace

- `lessons/` - one short HTML lesson per phase (0001-0010).
- `reference/` - reusable quick-reference teaching documents.
- `learning-records/` - evidence-backed learning records.

## Local Runtime Folders (never committed)

- `data/` - SQLite database and runtime data.
- `models/` - downloaded ONNX models (`scripts/download_models.py`).
- `logs/` - runtime logs.
- `recordings/` - local demo recordings.
