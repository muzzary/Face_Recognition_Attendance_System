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

`pip install -e .` above stays intentionally unpinned so contributors resolve flexibly. `requirements-lock.txt` records the exact resolved versions the project is verified against (CPython 3.13); CI installs with `pip install -e ".[dev]" -c requirements-lock.txt` for reproducible builds. After intentionally bumping a dependency, regenerate it from a clean virtualenv with `pip freeze --exclude-editable > requirements-lock.txt` (re-add the header) and commit.

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

### API

A read-only HTTP API (FastAPI) reports the stored roster and attendance over the same tenant-scoped storage layer, behind JWT auth and role-based access control. It has no write endpoints. `FA_JWT_SECRET` **must be set** before the API can issue or verify tokens (it fails loudly otherwise). Run it against the configured `FA_DATABASE_PATH`:

```powershell
$env:FA_JWT_SECRET = "<a long random secret>"
uvicorn face_attendance.api.main:app --reload
```

Routes (every data route is scoped by an `org_id` path segment, so a tenant only ever sees its own rows):

- `GET /health` — liveness check, no database access, no auth.
- `POST /auth/login` — JSON `{email, password}` → `{access_token, token_type: "bearer"}`; `401` on bad credentials (without revealing whether email or password was wrong).
- `GET /orgs/{org_id}/employees` — roster for the org (empty list if none). admin/manager only.
- `GET /orgs/{org_id}/employees/{employee_id}` — one employee, or 404. An `employee`-role user may only read their own record.
- `GET /orgs/{org_id}/attendance?employee_id=&limit=` — attendance events, optionally filtered and capped to the newest `limit`. An `employee`-role user is silently scoped to their own events.
- `POST /orgs/{org_id}/stream-ticket` — mints a 60-second, stream-only ticket (same org/role checks as `/stream`). Requires the normal `Authorization` bearer header.
- `GET /orgs/{org_id}/stream` — live annotated MJPEG feed (`multipart/x-mixed-replace`) from this org's single camera. admin/manager only (`employee` → `403`). The camera opens lazily on the first request to this route (not at API startup) and auto-releases after `FA_STREAM_IDLE_TIMEOUT_SECONDS` with no active viewers — the first viewer after a cold start or an idle release pays the documented 60–90s Windows camera-open cost. If no camera is available (dev/CI box, or models missing) the feature is disabled with a logged warning and this route returns `503` instead of hanging (the other routes keep working). **Auth:** a browser cannot set an `Authorization` header on the `<img>`/`<video>` `src` used to render MJPEG, so this route accepts a short-lived `?ticket=<jwt>` minted by `POST /stream-ticket` (the header is still preferred when present). The long-lived access token is never accepted here — only a stream ticket, scoped to a separate audience and a 60-second lifetime, can authorize this route.

**Auth model:** every data route requires a valid bearer token whose `org_id` claim matches the URL (else `403`). Roles are `admin`, `manager`, `employee`. `admin` and `manager` have identical full read scope in this phase — there is no team/manager hierarchy data model yet, so `manager` is deliberately equivalent to `admin`. `employee` is restricted to their own linked record. Passwords are hashed with PBKDF2-HMAC-SHA256 (stdlib); tokens are HS256 JWTs signed with `FA_JWT_SECRET`.

### Web Frontend

A React + TypeScript + Vite single-page app in [`frontend/`](frontend/README.md) gates on a login form, then renders role-appropriate dashboards: admin/manager get the roster, an org-wide attendance report, and a **Live camera** panel (the MJPEG feed rendered in a plain `<img>`, with a clear "unavailable" message if the camera stream `503`s); the `employee` role gets a self-service view (own attendance only, no roster, no live feed). Run the two halves together locally: seed a dev DB and start the API (`python scripts/seed_dev_data.py` then, with `FA_JWT_SECRET` set, `uvicorn face_attendance.api.main:app --reload`), then `cd frontend && npm install && npm run dev` (http://localhost:5173, which the API's dev CORS allow-list permits). The seed script prints local dev logins (`admin@acme.test` / `manager@acme.test` / `employee@acme.test`, password `devpassword123`). The live feed needs the API host to have a working camera and the ONNX models downloaded (`python scripts/download_models.py`); without them the panel shows the unavailable message and the rest of the dashboard still works.

### Configuration

All tunables are environment variables validated at startup (defaults in parentheses):

| Variable | Meaning |
|---|---|
| `FA_DATABASE_PATH` | SQLite file (`data/attendance.db`) |
| `FA_ORG_ID` | organization (tenant) this terminal reads and writes (`default`) — every employee, embedding, and attendance row is scoped to it, so separate companies' data can never mix. Single-org CLI deployments leave this alone; a terminal running for a specific company sets it to that company's id |
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
| `FA_STREAM_IDLE_TIMEOUT_SECONDS` | seconds the API keeps the camera open after the last live-feed viewer disconnects before auto-releasing it (`300`) — the camera opens lazily on the first `/stream` request (paying the Windows cold-start cost then, not at API startup) and a new viewer within this window cancels the pending release |
| `FA_JWT_SECRET` | secret that signs/verifies API JWTs — **no default**, required before the API can log anyone in or verify a token (fails loudly if unset). A real secret: set it via env only, never commit it. Camera-only CLI usage does not need it |
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

- **Matching:** all active embeddings live in one L2-normalized numpy matrix; a match is a single matrix-vector product. Benchmarked directly on a real 1000-employee × 5-sample gallery (5000 embeddings, 128 dims): index build **41 ms**, **414 microseconds per match** (2,418 matches/second). A recognition frame has a 100–500 ms budget at typical camera frame rates — matching consumes under half a millisecond of it, effectively free at this scale. Also regression-tested in CI.
- **Storage:** SQLite in WAL mode with a busy timeout; hot paths are indexed (`attendance_events(employee_id, occurred_at)`, `face_embeddings(employee_id)`, plus `org_id` on all three tenant-scoped tables so per-org reports and gallery loads filter on an index, never a table scan). Benchmarked with 1000 enrolled employees and 50,000 attendance events (roughly 1000 employees × 2 events/day × 25 days): enrollment **12.6 ms/employee** (negligible next to the seconds of camera/liveness capture it's part of), indexed last-event lookup **3.4 ms**, a `report` query over the full 50k rows **49.6 ms**. Attendance writes measured **~10.5 ms/event** — fine for the real workload (sparse, one event per employee every cooldown period, never a tight write loop) but not tuned for bulk throughput; each write currently opens its own SQLite connection rather than reusing one, which is where that fixed overhead comes from. A year of 1000 employees clocking twice a day is ~500k rows — comfortably inside SQLite's read envelope on one terminal.
- **Concurrency ceiling (honest limit):** SQLite is single-writer. The measurements above hold for **one terminal**. If a deployment grows into multiple simultaneous entry-point terminals writing to the same database file, writes would start to serialize/contend — not silently broken, but a real architectural boundary, not just a tuning knob.
- **Index refresh:** enrollment refreshes the in-memory gallery immediately, and a running attendance session re-reads it every `FA_INDEX_REFRESH_SECONDS` (default 30 s) — so deactivating an employee takes effect on live terminals within that window, no restart needed.
- **Growth path:** the storage repository, detector, and embedder sit behind interfaces — swapping SQLite→Postgres (which removes the single-writer ceiling above) or SFace→a stronger embedding model touches one adapter each, not the pipeline. A future cloud API can reuse `PipelineComponents` behind FastAPI without changing any module.

## Security & Privacy

- Biometric data is stored **only as numeric embeddings**; raw frames live in memory and are discarded. The schema is tested to contain no image/photo/raw/bytes columns.
- **Tenant isolation:** every employee, embedding, and attendance row carries an `org_id` (foreign-keyed to an `organizations` table), and every storage read filters by it — one organization's data can never surface in another's queries (tested per read method). The CLI is single-org today via `FA_ORG_ID` (defaults to the built-in `default` org). An existing pre-org (v2) database is upgraded in place with `migrate_to_org_scoping`, which backfills all existing rows to the default org with zero data loss.
- Original faces cannot be reconstructed from SFace vectors. Note that embeddings are still biometric templates and sit unencrypted in the SQLite file. This was an acceptable tradeoff for a single trusted terminal, but the system now also runs as a multi-tenant web API — OS-level disk encryption (e.g. BitLocker) on the host is required, and application-level at-rest encryption for embeddings should be added before any real production/cloud deployment with real biometric data.
- **The camera is only held while it is being watched.** The API opens the single camera lazily on the first live-feed request and auto-releases it after `FA_STREAM_IDLE_TIMEOUT_SECONDS` with zero viewers, so an idle API neither reserves the device (blocking the CLI's `enroll`/`attend`) nor runs recognition inference on a feed nobody is viewing.
- Enrollment is a single database transaction: a crash mid-enrollment can never leave a partial gallery.
- **A real secret is required for the web API.** `FA_JWT_SECRET` (32+ characters, no default) must be set before the API can issue or verify tokens — it fails loudly if unset. Set it via environment variable only, never commit it; it goes in a gitignored `.env` for local dev.
- Model downloads are SHA256-pinned; a tampered file never loads.
- `data/`, `logs/`, `models/`, `recordings/` are local runtime folders and never committed.

## Testing

```powershell
python -m unittest discover -s tests
```

150 tests cover every module with hardware-free fakes: capture failure modes, multi-face detection, enrollment quality gates, threshold behavior, spoof sequences (static/waved/rotated photo), liveness bands (motion ceiling, deformation floor, natural-head-turn regression guard), calibration recommendations, backpressure, worker failure policy, end-to-end enrollment/attendance, the MJPEG stream preview (latest-wins output holder, multipart framing, slow-consumer-never-stalls-producer), settings validation, and CLI dispatch. A scalability guard asserts 1000-employee matching latency. CI runs the suite on every push.

Tests that need real ONNX models skip automatically when models aren't downloaded, so CI needs no model fetch.

## Repository Layout

See [DIRECTORY_MAP.md](DIRECTORY_MAP.md). Build history and verification per phase: [docs/phase-log.md](docs/phase-log.md). Roadmap: [docs/project-plan.md](docs/project-plan.md).
