# Phase Log

## Manual Testing Complete - Scalability Verification

Date: 2026-07-08

### Summary

Manual testing (`docs/demo-checklist.md`) is complete: enrollment, live recognition with clock-in/out logging, still-photo spoof rejection, waved-photo spoof rejection, natural head-turn (no false reject, confirming the deformation-ceiling fix), and the `calibrate-liveness` tool (run twice, both times correctly warning against tightening the validated defaults).

User asked directly whether the system can scale to a 1000+ employee firm. Rather than repeat prior claims, benchmarked the current code directly:

### Matching (`EmployeeEmbeddingIndex`/`EmployeeMatcher`)

Real gallery: 1000 employees x 5 embeddings (5000 x 128-dim vectors), 2000 live matches run against it.
- Index build: 41 ms
- Match latency: 414 microseconds/match (2,418 matches/second)

### Storage (`AttendanceStorage`)

Realistic load: 1000 employee enrollments (atomic, 5 embeddings each), then 50,000 attendance events (~1000 employees x 2 events/day x 25 days).
- Enrollment: 12.6 ms/employee
- Attendance event write: ~10.5 ms/event
- Indexed last-event lookup: 3.4 ms
- Report query (`LIMIT 50`) over the full 50k rows: 49.6 ms

Root-caused the 10.5ms write cost: `AttendanceStorage._connect()` opens a fresh SQLite connection (and re-runs its PRAGMAs) on every call rather than reusing one. Fine for the real workload (sparse, cooldown-gated, one event per employee per interaction) but not tuned for bulk-write throughput. Documented as an honest limit, not silently glossed over, since a future high-frequency bulk-import or multi-terminal scenario would need connection reuse or a move to Postgres to avoid it becoming a bottleneck.

### Verdict (added to README)

Single terminal, 1000+ employees: matching is effectively free at this scale (sub-millisecond), and the realistic write rate never stresses the ~10ms/write storage layer. Multiple simultaneous terminals writing to the same SQLite file would contend on writes (SQLite is single-writer) - a real architectural ceiling, not a tuning problem, and exactly what the already-planned Postgres migration (for the eventual cloud deployment) removes.

### Verified

- `python -m unittest discover -s tests` (144 tests, all green)
- All benchmark numbers above measured directly against the current codebase in this session, not carried over from earlier estimates.

## Manual Test Follow-up - Calibration Tool Regression Guard

Date: 2026-07-08

### The problem

First real use of `calibrate-liveness` immediately exposed a flaw in the tool itself, not just the numbers it measures. A 20-second calibration session on the same camera/machine already validated across four prior manual test rounds measured:

- motion observed range: 0.0135 - 0.0672
- recommended `FA_LIVENESS_MAX_MOTION`: 0.0874 (0.0672 * 1.3 margin)

But an earlier session's `docs/phase-log.md` entry recorded a legitimate, non-hectic PASSING reading of `motion=0.1099` on this exact camera. Adopting the new tool's recommendation would have set the ceiling *below* a value already proven to be normal live behavior - reintroducing the false-reject bug fixed two entries above this one, caused by the calibration tool itself rather than a bad guess.

Root cause: a single short session can under-sample the true range of natural human movement. The recommendation formula (`observed_max * margin`) is only as good as how representative the sampled session was, and nothing in the original tool compared its output against what was already configured and validated.

### The fix

- `print_calibration_report` now takes the currently configured `FA_LIVENESS_MAX_MOTION`/`FA_LIVENESS_MIN_DEFORMATION` and compares against them:
  - If the recommended motion ceiling is **tighter** (lower) than what's configured, prints an explicit warning: a single short session can under-sample movement variety, and narrowing an already-validated ceiling risks reintroducing false rejects. Recommends a longer `--duration`, multiple runs, or multiple real users before tightening.
  - If the recommended deformation floor is **lower** than what's configured, prints a different warning: this makes the spoof-rejection check *more permissive* (security-weakening direction), and should only be adopted with specific evidence the current floor false-rejects genuine users.
  - A recommendation that *widens* either value (safer direction, accommodating a noisier/slower camera) prints without a warning.
- CLI wires the actual current `AppSettings` values through, so the comparison reflects whatever is really configured (including prior env-var overrides), not just the shipped defaults.
- README updated to state this happened during real testing, not hypothetically, and to tell operators to read the warning before adopting a narrower number.

### Verified

- `python -m unittest discover -s tests` (144 tests, all green)
- Replayed the user's actual reported calibration output through the fixed report function directly: correctly prints the "TIGHTER" warning for motion and the "MORE permissive" warning for deformation.

### Review

- Clean: a widening recommendation (the safe direction) still prints without noise, so the warning stays meaningful when it does appear.
- This is the second time in this liveness work that a plausible-looking, formula-driven number turned out to be wrong only once checked against previously validated real data (the first was the v2 deformation ceiling). Both times the fix was to make the tooling itself surface the check, not to rely on remembering to do it manually every time.

## Manual Test Follow-up - Per-Camera Liveness Calibration Command

Date: 2026-07-08

### Changed

- After confirming the deformation-ceiling fix, the user asked a sharp question: don't the calibrated motion/deformation numbers depend on the specific camera? Yes - three camera-specific factors feed directly into them: landmark-detector pixel-noise floor (sensor/lighting dependent), achievable processing frame rate (motion is measured between *consecutively processed* frames, so a slower camera/pipeline inflates the same physical movement), and standing distance (noise doesn't shrink proportionally with the normalizing inter-ocular distance). This matters for a system meant to scale across multiple terminals/cameras, not just one laptop.
- Added `face-attendance calibrate-liveness [--camera-index N] [--duration 20]`: runs a short live session, collects real motion/deformation samples using the exact same computation the liveness gate uses (via a permissive, non-gating `MicroMovementLivenessChecker`), and prints the observed range plus recommended `FA_LIVENESS_MAX_MOTION`/`FA_LIVENESS_MIN_DEFORMATION` values for that specific camera (peak-observed-motion + 30% margin; deformation floor tightened only if the camera proves quieter than the shipped default, never loosened without evidence).
- New module `src/face_attendance/app/calibrate.py`; `run_liveness_calibration` takes an injectable `clock` callable so tests drive it deterministically instead of racing real wall-clock time against fakes.
- `_require_models` in the CLI gained a `need_sface` flag so this command only requires the YuNet model (it doesn't need SFace embeddings).

### Verified

- `python -m unittest discover -s tests` (142 tests, all green)
- CLI fails fast with a clear message when the YuNet model is missing, without touching the camera (confirmed in isolation: 0.05s, no hardware access).

### Review

- Clean: formalizes the exact manual process used throughout this session's liveness debugging (print raw values, compare live vs spoof, set thresholds from evidence) into a repeatable setup step for any new terminal.

## Manual Test Follow-up - Deformation Ceiling Removed (False-Reject on Natural Head Turns)

Date: 2026-07-08

### The problem

The very next manual test after shipping the v2 band redesign found a false reject: a clean, isolated test with zero photo involved ("just move naturally like arriving at work") produced a liveness FAILURE.

Two evaluations from that clean session:
- Calm: `motion=0.0250, deform=0.0106` -> PASSED
- Same person, natural head turn (no photo): `motion=0.0290, deform=0.0228` -> FAILED ("tilted rigid object")

Motion barely moved (0.0250 -> 0.0290); deformation more than doubled (0.0106 -> 0.0228), crossing the v2 ceiling (0.020). Root cause: turning your head is *also* an out-of-plane rotation. The deformation metric only corrects for translation, scale, and in-plane rotation - it cannot distinguish a live person turning their head from a spoof photo being tilted, because both produce the same kind of uncorrected residual. The v2 ceiling, calibrated from a *calm, sitting-still* session, was never going to survive contact with normal human movement (turning to glance around, nodding) at a real entrance.

### Investigation

Replayed every real measured reading collected across all liveness test sessions so far (four separate manual test rounds) against both the motion and deformation signals:
- **Motion** held a real, consistent gap in every session: live never exceeded ~0.11 (closest live pass was 0.1093), every clean isolated spoof test measured 0.1569 or higher (up to 4.24 for vigorous waving).
- **Deformation** did not: live "passing" values crept up to 0.0195-0.0200 (right at the v2 ceiling) even during ordinary use, and spoof-attributed deformation readings from a mixed test session overlapped heavily with that same range - no safe margin, unlike motion.

### The fix

- `MicroMovementLivenessChecker`: deformation ceiling removed entirely; only the floor remains (`min_deformation`, unchanged at 0.003 from v2). Motion keeps its full two-sided band (`0.004`-`0.11`, unchanged - it was never the problem). `LIVENESS_METHOD` bumped to `micro-movement-v3`.
- The floor alone still catches a photo moved with pure in-plane motion (translation/rotation only, no tilt) that might otherwise stay under the motion ceiling while never truly deforming.
- `AppSettings.liveness_max_deformation` and its cross-field validator removed; `FA_LIVENESS_MAX_DEFORMATION` is no longer a recognized variable.
- `tests/test_liveness.py`: added `test_natural_head_turn_passes_despite_elevated_deformation` (synthetic low-motion/high-deformation sequence, the exact case that just failed on real hardware) as a permanent regression guard; `hand_held_photo_sequence`'s parameters retuned so it still reliably exceeds the motion ceiling now that motion uses median (more outlier-robust) rather than mean.

### Verified

- `python -m unittest discover -s tests` (132 tests, all green)
- Replayed all real measured readings from every prior session (calm live, clean spoof, mixed live+spoof, and this clean live-movement session) through the fixed logic directly: every live reading passes (including the one that previously false-rejected), both spoof readings still correctly fail.

### Review

- Clean: no change to motion's band, which has held up across every real session so far and was never implicated in this bug.
- Honest: README now documents the full v1 -> v2 -> v3 history so the reasoning survives future recalibration, not just the current numbers.

## Manual Test Follow-up - Liveness Band Redesign (Blink Detection Investigated and Rejected)

Date: 2026-07-08

### The problem

Manual testing with real metric visibility (previous entry) surfaced two findings:
1. A live face's own deformation readings (0.0044-0.0152) straddled the old floor threshold (0.006), so the SAME person's live session flickered between PASSED and FAILED roughly every other evaluation.
2. A hand-held still-photo spoof measured motion=0.1962 and deformation=0.0286 - both **higher** than the live face's own maximum (0.0848 / 0.0152). A floor-only check cannot separate these: any threshold high enough to reject the spoof would also reject the live face's quieter moments; any threshold low enough to admit live lets the spoof straight through. The original design assumption ("spoof = too still") was backwards for a hand-held attack: a trembling hand moves and tilts more than a calm, authenticating face.

### Blink detection: investigated, verified feasible, then rejected

At the user's direction, pursued real blink detection as a stronger, independent liveness signal:
- Confirmed `opencv_zoo` (the project's existing trusted model source) has no facial-landmark/eye-contour model.
- Researched alternatives: MediaPipe (rejected - no official Python 3.13 support, this project's runtime) and InsightFace's `2d106det` landmark model (5MB, ONNX, MIT-licensed code / non-commercial-research-licensed weights - accepted by the user for this assignment context).
- Downloaded `2d106det.onnx` from two independent HuggingFace mirrors with explicit user approval (byte-identical SHA256 across both, confirming authenticity) after a permission gate correctly blocked fetching it from agent-selected, previously-unvetted sources.
- Reverse-derived the exact InsightFace preprocessing/postprocessing algorithm from their source (`landmark.py`, `face_align.py`) since their own README lacked sufficient detail; reimplemented the affine crop transform in pure numpy (no `scikit-image` dependency needed).
- Empirically discovered which of the 106 output indices correspond to each eye by cross-referencing against YuNet's own trusted eye landmarks across 30 real webcam frames (100% consistent index sets across all samples - not guessed from an unverified scraped table).
- Ran three real-camera calibration sessions (open-eyes, blink, and a deliberately-timed blink test with explicit "3...2...1...BLINK NOW" cues). Result: **inconclusive on two attempts, then outright failure on the third** - after ~6s into the final test, every subsequent frame lost face detection entirely.
- Root-caused via a controlled A/B test: a camera-only `read()` loop delivered 90/90 fresh frames over 9s with zero duplicates; the combined YuNet+landmark106 pipeline periodically stalled for ~1.07s per frame and eventually stopped detecting faces at all for the remainder of a session. Conclusion: this development machine's webcam/driver cannot reliably sustain the added per-frame inference load blink detection requires. Shipping it would make the *existing* recognition pipeline less reliable, not just add a feature.
- Decision (with user): abandon blink detection. `models/2d106det.onnx` removed (was never wired into the shipped `model_files.py`/CLI).

### The shipped fix

- `MicroMovementLivenessChecker` redesigned around `_Band(low, high)` for both motion and deformation, replacing the one-sided floors. New defaults anchored to the real measured live/spoof data above (see README table): motion `[0.004, 0.11]`, deformation `[0.003, 0.020]`.
- Window size default raised 12 → 16 frames for more temporal averaging.
- `_centroid_motion` switched mean → median; `_non_rigid_deformation` switched std → scaled MAD (median absolute deviation) - both more robust to a handful of noisy frames dominating the estimate.
- New failure reasons distinguish "too little" (mounted/static photo) from "too much" (hand-held photo/erratic) on both signals.
- `AppSettings` gained `liveness_max_motion`/`liveness_max_deformation` with a model-level validator rejecting an inverted band (`min >= max`) at startup.
- Replayed all real measured live-session and spoof readings through the new band logic directly: every live reading now passes consistently (no more flicker); both spoof readings correctly fail.

### Verified

- `python -m unittest discover -s tests` (131 tests, all green)
- Real data replay (not synthetic): 18/18 live readings PASS, 2/2 spoof readings FAIL under the new bands.

### Review

- Clean: no new dependency, no new per-frame model, no change to camera load - the fix stays entirely within the existing 5-point YuNet landmark data already being computed.
- Honest: README documents the video-replay gap (unchanged) and now also the blink-detection investigation and why it was abandoned, plus the fact that bands are calibrated to one real setup and should be re-verified on a different camera.

## Manual Test Follow-up - Liveness Metric Visibility for Calibration

Date: 2026-07-08

### Changed

- A manual test showed a CLOCK_IN logged for what the user believed was a still-photo spoof attempt. Root-cause theory: `FA_LIVENESS_MIN_MOTION`/`FA_LIVENESS_MIN_DEFORMATION` (0.004/0.006) were conservative guesses made before any real-hardware calibration was possible, and natural hand tremor while holding a phone/photo can plausibly exceed such small thresholds. Rather than guess new numbers, added visibility into the actual measured values so real-hardware data drives the threshold, not a guess.
- `LivenessResult` gained optional `motion`/`deformation` fields (`>= 0`, `None` while gathering evidence), populated by `MicroMovementLivenessChecker` on every full-window evaluation.
- `attend`'s console output now appends the raw values to every liveness message, e.g. `... [motion=0.0012]` or `... [motion=0.0150, deform=0.0200]` on a logged clock-in - printed once per state change (dedupe still keys on the stable reason text, not the fluctuating numbers, so this does not reintroduce per-frame spam).
- Added `tests/test_attend_reporting.py` (metrics-suffix formatting, dedupe-with-metrics behavior, passing-metrics on a logged event) and extended `test_liveness.py`/`test_contracts.py` for the new fields.

### Verified

- `python -m unittest discover -s tests` (126 tests, all green)

### Pending

- Re-run the manual live-face and static/waved-photo tests with this build to capture real motion/deformation numbers, then set `FA_LIVENESS_MIN_MOTION`/`FA_LIVENESS_MIN_DEFORMATION` from that evidence.

## Manual Test Follow-up - Camera Open Progress Messaging

Date: 2026-07-08

### Changed

- User reported `attend` "getting stuck" on a second run after the first ran fine. Reproduced directly: a fresh-process `cv2.VideoCapture(0, cv2.CAP_DSHOW)` open took 90.1s on this hardware after the camera had been idle, versus 0.4-0.5s once "warm" (confirmed the same call twice in one process: 90.1s then 0.4s). Root cause is Windows-level, not application logic: `Get-Service FrameServer` showed `Stopped`/`Manual` — the Frame Server that arbitrates camera access demand-starts on first access after idling, and video driver DLLs can be scanned by antivirus on first load. `cv2.VideoCapture()` has no timeout knob, so the app was silent for up to 90s, indistinguishable from a real hang.
- `_make_camera` in `cli.py` now prints "Opening camera..." immediately and a background daemon thread prints a reassurance line every 5 seconds while the (still-blocking) open call is in flight, so a slow cold start reads as "waiting" instead of "frozen". No behavior change to the camera/backend logic itself - this is observability only.
- Documented the behavior honestly in the README: this is OS-level latency we cannot shorten, most noticeable after camera idle time.

### Verified

- `python -m unittest discover -s tests` (117 tests, all green)
- Reproduced the slow cold-open directly via PowerShell diagnostics (90.1s cold, 0.4-0.5s warm, confirmed 3x).
- Confirmed `FrameServer` Windows service is demand-started (`Manual`) and was `Stopped` at the time of the slow open.

### Review

- Clean: this cannot be fixed by the application (native blocking call, OS service cold start); messaging is the correct and honest mitigation. The backend cache (previous entry) still saves the MSMF-probe portion of the delay; this entry addresses the remaining DirectShow-itself cold-start cost.

## Manual Test Follow-up - Camera Backend Cache

Date: 2026-07-08

### Changed

- The auto backend probe made every fresh launch pay 10-20 s before falling back to DirectShow on this machine. Added `capture/backend_cache.py`: after a successful auto probe, the working backend is stored in `data/camera_backend.json` (per camera index) and tried first on later launches; a stale cache entry (camera swapped, driver change) is discarded and re-probed automatically.
- `OpenCvCamera` now exposes `backend_used`; the CLI opens cameras via `open_camera_remembering_backend`.
- Cache is an optimization only: unreadable/corrupt cache files are ignored with a warning, never fatal.

### Verified

- `python -m unittest discover -s tests` (117 tests, all green)
- Real hardware: first open 18.9 s (probe + store), second open 0.9 s (cached, DirectShow).

### Review

- Clean: forced backends (`FA_CAMERA_BACKEND=dshow` etc.) bypass the cache entirely; cache stores only concrete backend names, never "auto".

## Manual Test Follow-up - Camera Backend Fallback

Date: 2026-07-07

### Changed

- First manual enrollment attempt failed: this machine's webcam opens under OpenCV's default Windows backend (MSMF) but never delivers frames (`OnReadSample error -2147023169`); DirectShow works.
- `OpenCvCamera` now verifies at open time that the chosen backend actually delivers a frame, and with `backend="auto"` (default) falls back to DirectShow on Windows; the chosen backend and fallback reason are logged.
- Added `FA_CAMERA_BACKEND` setting (`auto`/`default`/`msmf`/`dshow`) wired through settings and CLI.
- Injected capture factories (tests, custom rigs) bypass probing, so all prior capture tests are unchanged.

### Verified

- `python -m unittest discover -s tests` (109 tests, all green)
- Real hardware: auto backend rejected MSMF after probe and delivered 640x480 frames via DirectShow.

### Review

- Clean: when every backend fails, the error lists each backend's failure reason plus a pointer to Windows camera privacy settings.

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

## Phase 12 - Review Fixes and Submission Polish

Date: 2026-07-07

### Changed

Independent code-review pass over phases 4-11 (verdict: no critical issues; four important findings, all fixed):

- **Thread-safety:** `worker_errors` in the attend loop is now lock-protected alongside `outputs` (a worker append during main-loop iteration could raise `RuntimeError: deque mutated during iteration` exactly when errors were being reported).
- **Atomic enrollment:** new `AttendanceStorage.add_employee_with_embeddings` inserts the employee and all embeddings in one transaction; a crash mid-enrollment can no longer leave a partial gallery behind a taken employee ID.
- **Live deactivation:** attendance sessions now refresh the in-memory gallery every `FA_INDEX_REFRESH_SECONDS` (default 30 s), so `employees deactivate` takes effect on running terminals; index refresh also builds the new snapshot before swapping (a failed rebuild keeps the last good gallery).
- **Liveness under load:** track-loss detection now uses wall-clock gaps (`FA_LIVENESS_MAX_GAP_SECONDS`, default 2 s) instead of frame ids — on slow hardware, dropped frames could previously reset the evidence window forever, locking everyone out.

Suggestions also applied: worker shutdown failure no longer skips camera/window cleanup; results landing during shutdown are drained and reported; cooldown messages are dedupe-stable; YuNet edge clamping shrinks boxes instead of shifting them; worker error-policy docstring corrected; `report --limit` rejects non-positive values; CLI pre-checks model files before opening the camera; README documents the plaintext-embedding tradeoff and the linger-toggle behavior.

Also: fixed the stale Phase 1 structure test that asserted removed dependency extras; version bumped to 1.0.0.

### Verified

- `python -m unittest discover -s tests` (106 tests, all green; also green with DeprecationWarnings as errors)
- Measured match latency: 0.95 ms at 1000 employees x 5 samples (5000x128 gallery).
- WAL mode, schema v2, and both hot-path indexes confirmed on a fresh database.
- CLI smoke: init-db, employees list, report, attend fail-fast without models, attend fail-fast message before camera open.

### Review

- Reviewed, clean after fixes. Remaining documented limitations: video-replay spoofs (README), unencrypted embeddings at rest (README), unverified model hashes pending network (see Phase 11 note).

### Pending (network was down this session)

- `python scripts/download_models.py` + confirm pinned SHA256 hashes.
- `git push` all phase commits.
- User manual checkpoints: webcam capture, enrollment, live recognition, spoof tests per `docs/demo-checklist.md`.

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
