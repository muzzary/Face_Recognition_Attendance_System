# Directory Map

Last updated: 2026-07-10 (Web Arc Phase 3: read-only API)

## Root

- `.gitignore` - ignores Python caches, virtual environments, secrets, runtime logs, recordings, downloaded models, and local biometric data.
- `AGENTS.md` - project-specific working instructions and engineering standards.
- `DIRECTORY_MAP.md` - quick navigation map for every important folder and file.
- `MISSION.md` - teaching mission for learning the project while building it.
- `RESOURCES.md` - curated source list for learning and implementation decisions.
- `NOTES.md` - teaching and collaboration notes.
- `pyproject.toml` - packaging metadata, core dependencies (pydantic, numpy, opencv-python, fastapi, uvicorn), the `httpx` dev dependency (FastAPI TestClient), and the `face-attendance` console script.
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
- `api/` - read-only FastAPI app over the storage layer: `main.py` (org-scoped employee/attendance/health routes reusing the `EmployeeRecord`/`AttendanceEvent` contracts as response models), `dependencies.py` (`get_storage`/`get_settings` DI so tests can point at a temp database). No auth or write endpoints yet.

## Frontend (`frontend/`)

React + TypeScript + Vite single-page app (Web Arc Phase 4 skeleton) that reads the roster and recent attendance from the API and renders them as plain HTML tables. No auth, styling, or routing yet.

- `package.json`, `vite.config.ts`, `tsconfig.json`, `index.html` - Vite `react-ts` scaffold; `vite.config.ts` also holds the Vitest (jsdom) config.
- `src/main.tsx` - React root mount.
- `src/App.tsx` - the single screen: hardcoded `acme` org, fetches employees + attendance from `http://127.0.0.1:8000`, with loading and "Failed to reach API" states.
- `src/App.test.tsx` - Vitest + React Testing Library tests (mocked `fetch`): employee/attendance rows render, error state on fetch failure.
- `src/setupTests.ts` - jest-dom matcher registration for Vitest.
- `README.md` - install/run instructions and the backend prerequisite.

## Scripts

- `scripts/download_models.py` - thin CLI wrapper around `face_attendance.model_files`.
- `scripts/seed_dev_data.py` - dev-only seeder: writes an `acme` org with a small roster and attendance events straight through `AttendanceStorage` (no camera) so the frontend has real rows to render.
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
- `tests/test_api.py` - read-only API via FastAPI TestClient against a temp SQLite DB: employee roster/single-lookup (incl. 404), attendance list with `limit`/employee filter, and cross-route tenant isolation on a two-org database.

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
