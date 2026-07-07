# Face Recognition Attendance System

Production-oriented biometric attendance system in Python: live video capture, face detection, embedding-based employee matching, multi-frame anti-spoofing liveness, and secure clock-in/clock-out logging — with **no raw face images ever stored**. Designed to stay fast and accurate at up to ~1000 enrolled employees per terminal.

## How It Works

```
camera ──▶ capture ──▶ latest-frame slot ──▶ recognition worker (background thread)
 (main thread, stays smooth)   (stale frames        │
                                dropped)            ├─ YuNet face detection (multi-face)
                                                    ├─ SFace 128-d embeddings
                                                    ├─ vectorized cosine matching vs gallery
                                                    ├─ multi-frame liveness (micro-movement)
                                                    └─ attendance decision ──▶ SQLite (WAL)
```

Every module boundary exchanges validated Pydantic contracts; cv2 types never leak past their adapters.

## Setup

Python 3.10+ on Windows, macOS, or Linux.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1          # Windows
python -m pip install -e .
python scripts/download_models.py     # fetch pinned YuNet + SFace ONNX models (~40 MB)
face-attendance init-db
```

Dependencies are deliberately minimal: `pydantic`, `numpy`, `opencv-python`. Detection (YuNet) and embeddings (SFace) ship inside OpenCV, so there is no dlib/onnxruntime install pain. Model files are hash-verified on download and gitignored.

## Usage

```powershell
# Enroll an employee (captures 5 quality-checked samples from the webcam)
face-attendance enroll --employee-id EMP-001 --name "Ada Lovelace"

# Run live attendance (video window; press q to quit). Add --no-display for headless.
face-attendance attend

# Reports and roster management
face-attendance report [--employee-id EMP-001] [--limit 50]
face-attendance employees list
face-attendance employees deactivate --employee-id EMP-001
face-attendance employees activate --employee-id EMP-001
```

`python -m face_attendance.cli ...` works identically to the `face-attendance` script.

### Configuration

All tunables are environment variables validated at startup (defaults in parentheses):

| Variable | Meaning |
|---|---|
| `FA_DATABASE_PATH` | SQLite file (`data/attendance.db`) |
| `FA_MODELS_DIR` | ONNX model directory (`models`) |
| `FA_CAMERA_INDEX` | camera device index (`0`) |
| `FA_SIMILARITY_THRESHOLD` | cosine match threshold (`0.363`) |
| `FA_DETECTION_SCORE_THRESHOLD` | YuNet face score floor (`0.8`) |
| `FA_ENROLLMENT_SAMPLES` | samples per enrollment (`5`) |
| `FA_ENROLLMENT_MIN_FACE_SIZE` | min face box in px (`80`) |
| `FA_LIVENESS_WINDOW_SIZE` | frames of liveness evidence (`12`) |
| `FA_LIVENESS_MIN_MOTION` | motion floor, rel. to eye distance (`0.004`) |
| `FA_LIVENESS_MIN_DEFORMATION` | non-rigidity floor (`0.006`) |
| `FA_LIVENESS_MAX_GAP_SECONDS` | track lost after this silence (`2.0`) |
| `FA_COOLDOWN_SECONDS` | per-employee re-log cooldown (`60`) |
| `FA_INDEX_REFRESH_SECONDS` | live gallery reload interval (`30`) |
| `FA_LOG_DIR`, `FA_LOG_LEVEL` | logging (`logs`, `INFO`) |

An invalid or unknown `FA_*` variable stops startup with the variable named.

## Matching Threshold (rationale)

Matching uses cosine similarity between SFace embeddings. The default threshold **0.363** is OpenCV's published operating point for SFace on standard benchmarks: scores ≥ 0.363 indicate the same identity.

- **Raising** the threshold reduces false accepts (an impostor logged as someone else) at the cost of more false rejects (a real employee bounced).
- Attendance systems should prefer false rejects — a bounced employee retries in seconds; a false accept silently corrupts payroll records.
- Every event stores its confidence score and match distance, so the threshold can be tuned later from real data (`face-attendance report` shows both).

With 1000 employees the *gallery* grows but the decision stays a single threshold on the best score; monitor near-threshold events in reports to detect drift (lighting changes, camera swaps).

**Clock-in/out semantics:** events toggle per employee (in → out → in) with a cooldown (`FA_COOLDOWN_SECONDS`, default 60 s) suppressing duplicates. An employee who lingers in front of the camera *longer than the cooldown* will toggle again (spurious clock-out); site the camera so people pass rather than loiter, or raise the cooldown for your deployment.

## Liveness: What It Catches and What It Doesn't

Liveness is multi-frame (`FA_LIVENESS_WINDOW_SIZE`, default 12 frames per identity) using two signals on facial landmarks, both normalized by inter-ocular distance (resolution- and distance-independent):

1. **Motion presence** — live heads always drift slightly. A pixel-still landmark window ⇒ *static photo* ⇒ rejected.
2. **Non-rigid deformation** — after removing translation, scale, and in-plane rotation per frame, a hand-waved photo or a screen showing a still image leaves ~zero residual movement, while a live face keeps deforming ⇒ rigid motion ⇒ rejected.

Attendance is **never** logged until liveness passes; an incomplete window is UNKNOWN, and UNKNOWN never logs.

**Honest limitations:**
- A screen **replaying a video** of the employee produces non-rigid motion and is *not* caught by this method. Defeating video replay requires texture/moiré analysis, depth sensing, or challenge-response — out of scope here and documented as the main residual risk.
- Default thresholds are conservative; verify them against your camera with the demo checklist (`docs/demo-checklist.md`) and tune via `FA_LIVENESS_*` if needed.

## Concurrency & Backlog Strategy

- The **capture loop** (main thread) only reads frames, hands them to the pipeline, and draws the latest results — it never blocks on model inference, so the preview stays smooth.
- Frames pass through a **single-slot mailbox** (`LatestFrameSlot`): a newer frame replaces an unconsumed one. Backlog is impossible *by construction* — when recognition can't keep up, stale frames are dropped and counted (reported in the session summary).
- One **recognition worker** thread runs detect → embed → match → liveness → attendance decision per frame, handling any number of faces per frame.
- **Error policy:** a bad frame is reported and survived; N consecutive failures (default 10) stop the worker loudly; shutdown is an event + join with timeout, and a hung worker raises instead of leaking.

## Scalability (1000-employee design)

- **Matching:** all active embeddings live in one L2-normalized numpy matrix; a match is a single matrix-vector product. 1000 employees × 5 samples × 128 dims ≈ 2.5 MB and multiplies in well under a millisecond (regression-tested).
- **Storage:** SQLite in WAL mode with a busy timeout; hot paths are indexed (`attendance_events(employee_id, occurred_at)`, `face_embeddings(employee_id)`). Reports use SQL `LIMIT`, not full scans. A year of 1000 employees clocking twice a day is ~500k rows — comfortably inside SQLite's envelope on one terminal.
- **Index refresh:** enrollment refreshes the in-memory gallery immediately, and a running attendance session re-reads it every `FA_INDEX_REFRESH_SECONDS` (default 30 s) — so deactivating an employee takes effect on live terminals within that window, no restart needed.
- **Growth path:** the storage repository, detector, and embedder sit behind interfaces — swapping SQLite→Postgres or SFace→a stronger embedding model touches one adapter each, not the pipeline. A future cloud API can reuse `PipelineComponents` behind FastAPI without changing any module.

## Security & Privacy

- Biometric data is stored **only as numeric embeddings**; raw frames live in memory and are discarded. The schema is tested to contain no image/photo/raw/bytes columns.
- Original faces cannot be reconstructed from SFace vectors. Note that embeddings are still biometric templates and sit unencrypted in the SQLite file — acceptable for a single trusted terminal; use OS-level disk encryption (e.g. BitLocker) on the device, and add at-rest encryption before any multi-tenant/cloud deployment.
- Enrollment is a single database transaction: a crash mid-enrollment can never leave a partial gallery.
- No secrets are needed today; if any are introduced, they go in `.env` (already gitignored).
- Model downloads are SHA256-pinned; a tampered file never loads.
- `data/`, `logs/`, `models/`, `recordings/` are local runtime folders and never committed.

## Testing

```powershell
python -m unittest discover -s tests
```

100+ tests cover every module with hardware-free fakes: capture failure modes, multi-face detection, enrollment quality gates, threshold behavior, spoof sequences (static/waved/rotated photo), backpressure, worker failure policy, end-to-end enrollment/attendance, settings validation, and CLI dispatch. A scalability guard asserts 1000-employee matching latency. CI runs the suite on every push.

Tests that need real ONNX models skip automatically when models aren't downloaded, so CI needs no model fetch.

## Repository Layout

See [DIRECTORY_MAP.md](DIRECTORY_MAP.md). Build history and verification per phase: [docs/phase-log.md](docs/phase-log.md). Roadmap: [docs/project-plan.md](docs/project-plan.md).
