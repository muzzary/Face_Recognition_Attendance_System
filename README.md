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
# On a new terminal/camera, calibrate liveness before trusting the defaults
face-attendance calibrate-liveness --duration 20

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
| `FA_CAMERA_BACKEND` | `auto`, `default`, `msmf`, `dshow` (`auto`) — auto probes the default backend and falls back to DirectShow on Windows if it opens but delivers no frames. The working backend is cached in `data/camera_backend.json`, so only the first launch pays the probe cost (~19 s → ~1 s measured) |

**Camera open can be slow and that's Windows, not this app.** `cv2.VideoCapture()` is a blocking native call with no timeout: on Windows, if the camera hasn't been used recently, the on-demand Frame Server service has to cold-start and the video driver DLLs may get scanned by antivirus — this has been observed taking 60-90 seconds with zero console output during the wait (measured on real hardware). The CLI now prints a reassurance message every 5 seconds while this is happening so it doesn't look hung. There is no application-level fix for this OS latency; it is most noticeable after the camera has been idle for a while and much faster on a "warm" camera.
| `FA_SIMILARITY_THRESHOLD` | cosine match threshold (`0.363`) |
| `FA_DETECTION_SCORE_THRESHOLD` | YuNet face score floor (`0.8`) |
| `FA_ENROLLMENT_SAMPLES` | samples per enrollment (`5`) |
| `FA_ENROLLMENT_MIN_FACE_SIZE` | min face box in px (`80`) |
| `FA_LIVENESS_WINDOW_SIZE` | frames of liveness evidence (`16`) |
| `FA_LIVENESS_MIN_MOTION` / `FA_LIVENESS_MAX_MOTION` | acceptable motion band, rel. to eye distance (`0.004` – `0.11`) |
| `FA_LIVENESS_MIN_DEFORMATION` | non-rigidity floor only, no ceiling (`0.003`) |
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

## Liveness: What It Catches, What It Doesn't, and Why Only Motion Is a Band

Liveness is multi-frame (`FA_LIVENESS_WINDOW_SIZE`, default 16 frames per identity) using two signals on facial landmarks, both normalized by inter-ocular distance (resolution- and distance-independent):

1. **Motion presence** — checked against an acceptable **band**, `FA_LIVENESS_MIN_MOTION` – `FA_LIVENESS_MAX_MOTION` (default `0.004` – `0.11`). Too little ⇒ mounted/still photo, rejected. Too much ⇒ hand-held photo, rejected (a trembling hand moves *more* than a calm, authenticating face — measured spoof motion was 0.1569–4.24, well above live's 0.0164–0.0848).
2. **Non-rigid deformation** — checked against a **floor only**, `FA_LIVENESS_MIN_DEFORMATION` (default `0.003`). After removing translation, scale, and in-plane rotation per frame, genuine facial movement leaves a small residual; near-zero residual means the "face" never actually deforms — a rigid object held perfectly still or waved with pure in-plane motion.

**This went through two real-hardware iterations before landing here** — worth reading because it explains why deformation isn't a band:

- **v1 (floor only, both signals):** a live face's own deformation readings (0.0044–0.0152) straddled the floor (0.006), so the *same* person's live session flickered pass/fail every other evaluation.
- **v2 (bands, both signals):** fixed the flicker by widening thresholds, but a hand-held spoof measured *higher* deformation (0.0286–0.0289) than live's own max (0.0152) — a ceiling on deformation could not admit live without also admitting that spoof. Shipped anyway with a ceiling, anchored to the measured data at the time.
- **v3 (shipped):** the v2 deformation ceiling then rejected a real employee's *natural head turn* — turning your head is *also* an out-of-plane rotation the in-plane-only correction can't remove, so it reads the same as a tilted spoof. Confirmed on real hardware: calm live deformation 0.0106 → same person just turning their head naturally, 0.0228 (more than double), motion barely changed (0.0250 → 0.0290). Deformation's ceiling was removed entirely; the floor (unchanged from v1) still catches a rigid object held with zero deformation. Motion's band, which held up consistently and safely across every real test session collected, remains the primary two-sided gate.

The full investigation, including every real measured reading, is in `docs/phase-log.md`.

**These specific numbers are tied to the camera, lighting, and processing speed they were measured on** — not universal constants. Three camera-specific factors feed directly into them: the landmark detector's pixel-noise floor (varies with sensor/lighting quality), the achievable processing frame rate (motion is measured between *consecutively processed* frames, not per-second — a slower camera/pipeline inflates the same physical movement into a larger value), and standing distance (noise doesn't shrink proportionally with the normalizing inter-ocular distance, so standing farther away inflates readings). For a deployment with multiple terminals on different camera hardware, run this on each one before trusting the defaults:

```powershell
face-attendance calibrate-liveness --duration 20
```

Move naturally during the recording (turn your head, glance around, nod — no photo). It reports the observed motion/deformation range and recommended `FA_LIVENESS_MAX_MOTION` / `FA_LIVENESS_MIN_DEFORMATION` values for that specific camera, then re-verify with the demo checklist (a live pass and a spoof rejection should still both hold).

**A single short run can recommend a *worse* value than an already-validated default — this happened in testing, not hypothetically.** A 20-second calm session measured a lower peak motion than earlier, more varied sessions on the same camera had already shown was normal; naively adopting its "recommended" (tighter) ceiling would have reintroduced the exact false-reject bug described above. The tool now compares its recommendation against whatever is currently configured and prints an explicit warning whenever it suggests *tightening* an existing value — read that warning before adopting a narrower number than what's already running, especially on a camera/threshold combination that's been through real validation.

Attendance is **never** logged until liveness passes; an incomplete window is UNKNOWN, and UNKNOWN never logs. Every liveness message printed by `attend` includes the raw measured values, e.g. `EMP-001: movement is more erratic than a natural head... [motion=0.1962, deform=0.0286]` or a passing `CLOCK_IN: ... [motion=0.0848, deform=0.0152]` — compare these against the `FA_LIVENESS_*` band settings to recalibrate for a different camera/lighting setup.

**Honest limitations:**
- A screen **replaying a video** of the employee produces non-rigid motion in the natural range and is *not* caught by this method. Defeating video replay requires texture/moiré analysis, depth sensing, or challenge-response — out of scope here.
- **Blink detection was investigated and abandoned.** A real ONNX 106-point landmark model (InsightFace `2d106det`, non-commercial-research license) was downloaded, hash-verified, and its eye-region points were empirically mapped against this project's own YuNet detector on real camera frames. It worked in isolation (~14ms/frame). But running it alongside the existing detection pipeline pushed combined per-frame CPU load high enough that this project's development webcam periodically **stopped delivering frames entirely** (confirmed: a camera-only loop ran flawlessly for 9s with zero dropped frames; adding the extra model caused runs where the back half of a 9s session lost 100% of frames). Adding a feature that makes the camera less reliable is a worse trade than not having it. The bands above are the result of that investigation redirected into the achievable fix.
- Bands are anchored to one real deployment's camera/lighting; a different setup should re-run the demo checklist and compare its own measured values against the defaults before trusting them.

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
