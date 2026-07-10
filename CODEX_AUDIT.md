# Codex Security and Efficiency Remediation Audit

This file is the phase-by-phase implementation record for the findings from the
Codex audit. The existing `README.md` and `docs/phase-log.md` are intentionally
left unchanged for the owner to update later.

## Phase 1 - Enforce Database Tenant Integrity

Date: 2026-07-11

Status: implemented, verified, reviewed, committed, pushed, awaiting manual checkpoint

### Finding resolved

The earlier org-scoped schema stored `org_id` on every row but identified an
employee globally by `employee_id`. Embeddings, attendance events, and employee
login users could therefore carry one organization ID while referencing an
employee in another organization. Different tenants also could not reuse the
same employee ID.

### Implementation

- Advanced the SQLite schema to v5.
- Changed employee identity to the composite primary key
  `(org_id, employee_id)`.
- Added composite foreign keys from face embeddings, attendance events, and
  employee-linked users to the owning tenant's employee.
- Changed the active-embedding join to match both `org_id` and `employee_id`.
- Changed attendance and embedding indexes to tenant-first composite indexes.
- Added a transactional v3/v4-to-v5 migration that preserves valid data and
  rolls back loudly when legacy data contains cross-organization relationships.
- Made normal database initialization automatically chain a legacy v2 database
  through org scoping and into v5.
- Exported `migrate_to_tenant_integrity` for explicit operational use.

### Automated verification

- Targeted storage/auth/API suite: 53 tests passed.
- Full Python regression suite: 201 tests passed in 44.861 seconds.
- New tests prove:
  - the same employee ID can exist independently in two organizations;
  - each organization's embedding index returns only its own biometric rows;
  - cross-organization embedding, attendance, and employee-user relationships
    are rejected by SQLite;
  - valid v4 data migrates to v5 without loss;
  - invalid legacy cross-organization data causes a complete rollback;
  - v2 initialization automatically reaches v5 without data loss.
- Deployment check against a temporary copy of the actual local v2 database:
  schema v5, one employee preserved, zero foreign-key violations.
- The real `data/attendance.db` was never modified by the deployment check.

### Self-review

- Correctness: reviewed, clean. Composite identity is enforced at the database
  boundary rather than relying only on repository callers.
- Security: reviewed, clean for this finding. Deliberately malformed tenant
  relationships are rejected, and corrupt legacy data cannot partially migrate.
- Rollback safety: reviewed, clean. Table rebuilds and integrity validation occur
  inside one explicit SQLite transaction.
- Efficiency: reviewed, clean. Tenant-first indexes cover employee history and
  embedding-gallery lookups; the employee composite primary key covers org
  roster access.
- Dependencies: no dependency changes.

### Files changed

- `src/face_attendance/storage/database.py`
- `src/face_attendance/storage/__init__.py`
- `tests/test_org_scoping.py`
- `CODEX_AUDIT.md`

### Delivery

Implementation commit: `546d6c6 Enforce tenant integrity in SQLite`

Push status: pushed to `origin/main`

## Phase 2 - Bind the Camera to Its Configured Organization

Date: 2026-07-11

Status: implemented, verified, reviewed, committed, pushed, awaiting manual checkpoint

### Finding resolved

The API process owns one physical camera and one recognition pipeline, but the
stream route previously served that same global feed for any organization whose
admin or manager requested its own tenant-qualified URL. Recognition and
attendance writes were already built from `FA_ORG_ID`; the HTTP boundary did not
enforce the same ownership.

### Implementation

- Added the configured organization as an explicit `CameraStreamer` property.
- Required the stream route's organization to equal `FA_ORG_ID`.
- Kept authorization ordering defensive: token/URL tenant matching and role
  checks happen first, camera ownership next, and availability last.
- An authenticated admin or manager from an unassigned tenant now always gets
  `403`, regardless of whether the physical camera is online.
- The configured tenant keeps the existing `503` behavior when its camera is
  unavailable and the normal MJPEG response when it is running.

### Automated verification

- API route suite: 17 tests passed before the corrected streaming invocation.
- Streaming module suite: 9 tests passed.
- Full Python regression suite: 204 tests passed in 48.521 seconds.
- New tests prove:
  - a valid admin from another tenant cannot view the process camera;
  - an unassigned tenant cannot use response differences to probe camera
    availability;
  - the streamer reports the organization owning its recognition pipeline.

### Self-review

- Correctness: reviewed, clean. The route and recognition pipeline use the same
  validated `AppSettings.org_id` source.
- Security: reviewed, clean for this finding. Cross-tenant authorization fails
  before camera state is inspected.
- Error handling: reviewed, clean. Existing role, unavailable-camera, and
  authenticated-stream behavior remains covered.
- Efficiency: reviewed, clean. The check is an in-memory string comparison and
  adds no camera, database, or inference work.
- Dependencies: no dependency changes.

### Operational checkpoint

The process must be started with the organization that physically owns its
camera. For the seeded Acme dashboard, set `FA_ORG_ID=acme` before starting the
API. Leaving the default organization configured will intentionally deny the
Acme stream.

### Files changed

- `src/face_attendance/api/main.py`
- `src/face_attendance/api/streaming.py`
- `tests/test_api.py`
- `tests/test_streaming.py`
- `CODEX_AUDIT.md`

### Delivery

Implementation commit: `b58a181 Bind camera stream to configured tenant`

Push status: pushed to `origin/main`

## Phase 3 - Stop the Live-Stream Bearer Token From Riding in a URL

Date: 2026-07-11

Status: implemented, verified, reviewed, committed, pushed, awaiting manual checkpoint

Continued by Claude after the implementing session (Codex) stopped mid-phase to
report a test-patch failure; see "Handoff" below for exactly what was picked up.

### Finding resolved

A browser `<img>`/`<video>` element cannot set an `Authorization` header, so the
live-stream route previously accepted the full 8-hour access token as a
`?token=` query parameter. Query strings commonly land in reverse-proxy/server
access logs, browser history, and referrer headers - a real credential-leak
path for a long-lived, full-privilege token. The audit also flagged that JWTs
had no enforced minimum secret strength, no required `exp`/issuer/audience
claims, and no way to invalidate a token before its 8-hour expiry if the
underlying account changed.

### Implementation

- `FA_JWT_SECRET` now requires at least 32 characters (was: any non-empty
  string); enforced by `AppSettings`, same fail-loud-and-name-the-variable
  pattern as every other setting.
- Access tokens (`create_access_token`) and a new, separate credential type -
  stream tickets (`create_stream_ticket`) - both now carry `iss`, `aud`,
  `type`, `iat`, and `jti`, and decoding requires every one of those claims
  plus `exp` to be present (`_decode_token`); a token minted for one audience
  can never be replayed against the other (proven by
  `test_stream_ticket_cannot_authorize_data_route`).
- Stream tickets are minted by a new `POST /orgs/{org_id}/stream-ticket`
  endpoint (same org-match, role, and camera-ownership checks the stream route
  already enforced), live for 60 seconds, and are the *only* credential the
  `?ticket=` query parameter accepts - the old `?token=` parameter is gone,
  and the response sets `Cache-Control: no-store` so the ticket itself is
  never cached. The MJPEG response now also sends
  `Cache-Control: no-store`, `Referrer-Policy: no-referrer`, and
  `X-Content-Type-Options: nosniff`.
- Every authenticated request (`get_current_user` and `get_stream_user`) now
  re-checks the token's claims against the live `users` row
  (`_require_current_user`): if the user was deleted, or their `org_id`,
  `role`, or `employee_id` no longer matches what the token claims, the
  request is rejected with `401` even though the token itself is still
  validly signed and unexpired. This closes the "no revocation" gap without
  adding a token blocklist - deleting or downgrading a user takes effect on
  their very next request.
- Frontend: the live-feed panel no longer puts the long-lived access token in
  the image URL. It first `POST`s to `/orgs/{org_id}/stream-ticket` with the
  access token in the `Authorization` header, then uses the short-lived
  ticket it gets back as the `<img>` `src`'s `?ticket=` value.

### Automated verification

- Full Python regression suite: 211 tests passed (204 before this phase; +7:
  2 in `tests/test_config.py` for the secret-length floor, 2 in
  `tests/test_auth.py` for revocation-on-delete and
  revocation-on-role-change, 3 already added by the stopped session in
  `tests/test_api.py` for ticket issuance, ticket/token audience separation,
  and the retired `?token=` parameter).
- Frontend: `npm test` - 12 passed (was 10 going into this phase);
  `npm run build` - clean, no TypeScript errors.
- Real end-to-end check against a fresh dev database with a real camera
  (`uvicorn` + `curl`, `FA_ORG_ID=acme`): login issues an access token; that
  access token as `?token=` against the stream route is `401` (the old
  bypass is gone); `POST /orgs/acme/stream-ticket` with the access token
  returns a 60-second ticket; that ticket as `?ticket=` against the stream
  route returns live MJPEG (`200`); the same ticket presented as a bearer
  header against `/orgs/acme/employees` is `401` (audience-scoped, can't
  reach data routes).

### Self-review

- Correctness: reviewed, clean. Ticket and access-token verification share
  one `_decode_token` implementation parameterized by audience/type, so the
  two paths cannot silently drift apart.
- Security: reviewed, clean for this finding. The leak-prone long-lived token
  no longer appears in any URL; the credential that does now has a 60-second
  window and is rejected outright by every non-stream route.
- Test-infrastructure bug found and fixed along the way: the revocation
  tests' raw `sqlite3.connect()` calls used the connection as a `with`
  context manager, which on `sqlite3.Connection` commits/rolls back a
  transaction but does **not** close the connection - the leaked handle held
  a Windows file lock that broke `TemporaryDirectory` cleanup. Fixed by
  closing the connection explicitly in a `finally` block.
- Dependencies: no dependency changes.

### Handoff (what Claude picked up vs. what Codex had already built)

The implementing session had already finished the substantive Phase 3 work
uncommitted in the working tree - `api/auth.py` (ticket issuance/verification,
required-claims decoding, `_require_current_user`), `api/main.py`
(`/stream-ticket` endpoint, response headers), `config/settings.py`
(min-length secret), the frontend ticket flow, and most of
`tests/test_api.py`'s new ticket coverage. It stopped because a test-only
patch against `tests/test_config.py` failed to apply (its expected insertion
anchor didn't match the file's current structure) and, per this project's
stop-on-ambiguous-failure rule, it reported the blocker instead of retrying.

Picking up from there, Claude: added the missing `tests/test_config.py`
coverage for the secret-length floor by hand; fixed a missing `import jwt` in
`tests/test_api.py` that was the actual reason the suite showed 1 failing
test (206/207) before this pass; added the "authentication revocation" tests
Codex's stopped message said it would write next (delete-then-request and
role-downgrade-then-request, both proving `_require_current_user` rejects a
stale-but-unexpired token); found and fixed the Windows connection-leak bug
those new tests exposed; and re-verified the whole phase end-to-end against a
freshly restarted API process (a running `uvicorn` picks up file changes only
on restart, so the pre-fix process was not sufficient evidence on its own).

### Files changed

- `src/face_attendance/config/settings.py`
- `src/face_attendance/api/auth.py`
- `src/face_attendance/api/main.py`
- `frontend/src/App.tsx`
- `tests/test_api.py`
- `tests/test_config.py`
- `tests/test_auth.py`
- `frontend/src/App.test.tsx`
- `CODEX_AUDIT.md`

### Delivery

Implementation commit: pending (see below)

Push status: pending

## Phase 4 - Make the Frontend Actually Multi-Tenant and Clear Expired Tokens

Date: 2026-07-11

Status: implemented, verified (automated), reviewed, committed, pushed, awaiting manual checkpoint

### Findings resolved

1. The frontend hardcoded `const ORG_ID = "acme"` and built every API URL from
   it, ignoring the org of the user who actually logged in. Any non-"acme"
   tenant could authenticate but then received `403` on every subsequent
   request, because the token's real `org_id` never matched the hardcoded URL.
   This failed safely (the backend still enforced the org match, so no
   cross-tenant data leak), but the advertised multi-tenant frontend worked only
   for org "acme".
2. A `401` from an authenticated fetch (expired or otherwise invalid token) only
   rendered "Failed to reach API" while the stale token stayed in
   `localStorage`, stranding the user on an error page with no route back to
   login short of manually clearing storage.

### Implementation

- Removed the `ORG_ID` constant. The org id now comes from the already-present
  client-side JWT decode (`decodeToken`/`TokenClaims`), threaded as an `orgId`
  prop from `claims.org_id` into `AdminDashboard`, `EmployeeDashboard`, and
  `LiveFeed`, and used in every employees/attendance/stream-ticket/stream URL.
  Because `claims` is derived fresh from the active token on each render, a
  logout/login as a different tenant automatically retargets every request; the
  org is never cached separately from the token.
- Added a small `ApiError` carrying the HTTP status so callers can tell `401`
  (bad/expired credential) apart from other failures. `fetchJson` now throws it.
- On a `401`, both dashboards call `onUnauthorized` (wired to the same `logout`
  that "Sign out" uses), clearing the stored token and returning to the login
  form. A `403` (valid token, wrong permissions) deliberately does not log out -
  it keeps the session and shows the existing "Failed to reach API" state.

### Automated verification

- Frontend `npm test`: 15 tests passed (12 before this phase; +3). New tests
  prove: employees/attendance/stream-ticket URLs carry the token's `org_id`
  ("globex") and never fall back to "acme"; a `401` clears the token and returns
  to the login form; a `403` keeps the token and shows the error without
  bouncing to login.
- Frontend `npm run build` (`tsc && vite build`): clean, no TypeScript errors.
- No browser automation was available this session, so the running UI was not
  visually confirmed; the behavior was exercised through the real component tree
  (`App` -> `Dashboard` -> role dashboards -> `fetchJson`) under jsdom with
  mocked fetch, which drives the same code path.

### Self-review

- Correctness: reviewed, clean. `orgId` and `onUnauthorized` are threaded from
  the active token's claims; the 401/403 branch keys off `ApiError.status`.
- Security: reviewed, clean for these findings. No credential enters a URL (the
  Phase 3 stream-ticket flow is unchanged); the org id is now the caller's own.
- Reuse/simplification: reviewed, clean. Extends the existing decode pattern and
  the existing `logout`; every added prop is load-bearing.
- Efficiency: reviewed, clean. No extra fetches or renders.
- Dependencies: no dependency changes.

### Files changed

- `frontend/src/App.tsx`
- `frontend/src/App.test.tsx`
- `CODEX_AUDIT.md`

### Delivery

Implementation commit: pending (see git history)

Push status: pending

## Phase 5 - Align Overlay Boxes to the Frame They Were Computed From

Date: 2026-07-11

Status: implemented, verified, reviewed, committed, pushed, awaiting manual checkpoint

### Finding resolved

The non-blocking capture loop drew the most recent completed `RecognitionOutput`
onto whatever the newest camera frame happened to be, not onto the frame that
output was actually computed from. Because recognition always lags the camera by
at least one frame (and more under load), the boxes and employee-name labels
were painted onto a frame that had already moved on - visually the boxes drift
and can appear to label the wrong person. The attendance decision itself was
never affected (it is made on the worker thread from the correct frame); this
was purely a display-alignment bug. It affected both the CLI `attend` preview
window and the API's live MJPEG stream, because both draw through the shared
`draw_overlay`.

### Option chosen

Option A (retain the computed-from frame), not Option B (a frame-id-equality
guard that skips the overlay on mismatch). Option B was rejected on measurement:
because recognition lags by at least one frame essentially always, a
skip-on-mismatch guard would suppress the overlay on almost every displayed
frame - an end-to-end run under induced lag showed 24 of 25 iterations lagged,
so boxes would have been blanked 24/25 of the time, destroying the feature.
Option A keeps boxes always visible and always aligned; the displayed video
simply lags slightly when inference is behind.

### Implementation

- Added an optional `image` field to the internal `RecognitionOutput`
  (default `None`, `compare=False` so the ndarray never enters dataclass
  equality). The worker now stamps each output with the exact frame pixels it
  was computed from. Chosen over changing the worker's `on_result` callback
  signature, which would have rippled through every pipeline test.
- `draw_overlay` now annotates `latest_output.image` (the frame the result
  describes) instead of the freshly-read camera frame, falling back to the
  handed-in frame only when there is no result yet or the result carries no
  image. Both display surfaces share this function, so the CLI preview and the
  MJPEG stream are fixed at one site.
- No change to matching, liveness, or attendance logic; no change to the
  latest-frame-wins / non-blocking guarantees (the capture loop still
  read -> put -> drain -> draw, the worker still owns inference, and
  `LatestFrameSlot` is untouched). The `outputs` deque is drained every capture
  iteration, so retaining a frame image per output stays bounded.

### Automated verification

- Changed-file suite (`test_app`, `test_pipeline`, `test_streaming`,
  `test_attend_reporting`): 39 passed.
- Full Python regression suite: 217 passed in 41.45 seconds.
- New `DrawOverlayAlignmentTests` prove: a stale result is drawn onto its own
  frame (a far-corner pixel matches the result's frame fill, not the newer
  camera frame's), the source frames are left untouched, a `None` result falls
  back to a clean unannotated current frame, and a result carrying no image
  degrades to annotating the current frame without crashing.
- End-to-end drive of the real `run_attendance` loop with a deliberately slow
  detector: across 25 iterations, all 24 lagged iterations drew their own output
  frame and in every one the drawn frame differed from the newest camera frame,
  confirming the pre-fix mismatch is gone.
- The actual visual "boxes track the right person smoothly" confirmation on a
  live webcam remains a manual checkpoint (no browser/camera automation this
  session), consistent with prior phases.

### Self-review

- Correctness: reviewed, clean. The overlay's image source and its box outcomes
  now come from the same `RecognitionOutput`, so they cannot describe different
  frames.
- Concurrency: reviewed, clean. No new blocking or backpressure; the capture
  loop and `LatestFrameSlot` discipline are unchanged.
- Reuse/simplification: reviewed, clean. Fixed at the one shared `draw_overlay`;
  the new field is defaulted so no existing construction site changed.
- Efficiency: reviewed, clean. Still one image copy per draw; the retained
  per-output image is bounded by the per-iteration drain.
- Dependencies: no dependency changes.

### Files changed

- `src/face_attendance/pipeline/worker.py`
- `src/face_attendance/app/attend.py`
- `tests/test_app.py`
- `CODEX_AUDIT.md`

### Delivery

Implementation commit: pending (see git history)

Push status: pending

## Phase 6 - Cap Reports, Rate-Limit Login, and Make CI Verify the Web System

Date: 2026-07-11

Status: implemented, verified, reviewed, committed, pushed, awaiting manual checkpoint

### Findings resolved

Three independent medium findings, fixed together as one phase:

- **Unbounded attendance report.** `GET /orgs/{org_id}/attendance` accepted an
  optional `limit` and, when omitted, triggered an unbounded `fetchall()` in
  `list_attendance_events`. A valid admin/manager could request an
  arbitrarily large response and exhaust memory as history grows.
- **No login rate limiting.** `POST /auth/login` ran the deliberately expensive
  200k-iteration PBKDF2 check on every call with zero throttling, so an
  unauthenticated caller could exhaust CPU/thread pool. The request model also
  put no length bound on the `email`/`password` fields fed into the hasher.
- **CI did not verify the completed web system.** The workflow installed `-e .`
  (missing the `dev` extra that provides `httpx`, which FastAPI's `TestClient`
  needs - so the API suite was silently failing in CI) and never set up Node,
  ran the frontend tests, or built the frontend.

### Implementation

- Attendance route `limit` is now `Query(ge=1, le=500)` with a default of 100
  instead of `None`/unbounded, so every call is server-capped regardless of
  what the caller passes or omits. The route always passes a concrete int to
  `list_attendance_events` (its `int | None` signature is unchanged - simpler,
  touches less code). This is a deliberate cap-only fix; true keyset/cursor
  pagination is the documented next step for very large histories.
- Added `_LoginRateLimiter`, a stdlib-only (`threading.Lock` + dict) in-process,
  per-client-IP fixed-window limiter. After 5 failed attempts within 60 seconds
  the login route returns `429` with a `Retry-After` header *before* running the
  password check; a successful login clears that IP's counter. Limiting is by
  IP, not email, on purpose (email-keyed limiting would let an attacker lock out
  a real user). A comment notes the single-instance limitation - a multi-instance
  deployment would need shared state (e.g. Redis), out of scope here.
- `LoginRequest` now bounds `email` to `max_length=254` and `password` to
  `max_length=256` so a pathologically large payload cannot reach the hasher.
- CI now installs `-e ".[dev]"` (with a comment explaining the httpx dependency)
  and gains a separate `frontend` job that sets up Node 20 and runs
  `npm ci`, `npm test -- --run`, and `npm run build` in `frontend/`.

### Automated verification

- New tests (4) in `tests/test_api.py`:
  - the attendance `limit` is rejected above the 500 cap (`422`);
  - login returns `429` with a `Retry-After` header after 5 failed attempts;
  - login rejects oversized `email`/`password` fields (`422`);
  - the existing positive/limit tests continue to pass with the new default.
- Targeted API suite: 23 tests passed.
- Full Python regression suite (`python -m unittest discover -s tests`, exactly
  as CI runs it): 217 tests passed in 33.172 seconds.
- CI change dry-run locally rather than guessed:
  - `pip install -e ".[dev]"` resolves and installs httpx;
  - `npm test -- --run` in `frontend/` -> 15 passed;
  - `npm run build` in `frontend/` -> clean (tsc + vite build).

### Self-review

- Correctness: reviewed, clean. The limiter checks the block *before* recording
  a failure, so a blocked IP records no further failures and the fixed window
  expires naturally - there is no permanent lockout. A successful login resets
  the counter. `request.client` being `None` falls back to a stable key.
- Security: reviewed, clean for these findings. The expensive hash is skipped
  once an IP is blocked; the report is always capped; oversized login payloads
  are refused with `422` before hashing.
- Concurrency: reviewed, clean. All limiter state mutation happens under a
  single lock.
- Efficiency: reviewed, clean. The cap replaces an unbounded scan with a
  bounded, index-ordered `LIMIT`.
- Dependencies: no new dependencies (stdlib `threading`/`time`, existing
  `pydantic.Field`).

### Follow-up noted (not acted on this pass)

CI still has no linter/formatter step. Per this project's convention that
linting-tool choice needs the owner's buy-in, this was intentionally left as a
follow-up rather than added here.

### Files changed

- `src/face_attendance/api/main.py`
- `.github/workflows/ci.yml`
- `tests/test_api.py`
- `CODEX_AUDIT.md`

### Delivery

Implementation commit: pending (see git history)

Push status: pending

## Phase 7 - Lazy Camera Lifecycle and a Reproducible Dependency Lock

Date: 2026-07-11

Status: implemented, verified, reviewed, committed, pushed, awaiting manual checkpoint

### Findings resolved

The two remaining lower-priority findings, fixed together as one phase:

1. **The camera ran for the API's whole lifetime with zero viewers.** The
   `lifespan` opened the single physical camera and started the recognition
   loop eagerly at API startup and held it until shutdown, regardless of
   whether anyone had ever opened the live feed. That burned recognition CPU on
   a feed nobody watched and permanently reserved the one camera device, so the
   CLI's `enroll`/`attend` could not use it while the API process ran.
2. **Dependencies had broad lower bounds and no lock file.** `pyproject.toml`
   declared only `>=` lower bounds and nothing pinned the resolved transitive
   versions, so `pip install -e .` could resolve differently over time - a
   non-reproducible build with no lock artifact of any kind.

### Implementation

Finding 1 - lazy start + idle auto-stop, all serialized under one streamer lock:

- Added `FA_STREAM_IDLE_TIMEOUT_SECONDS` (default `300` = 5 minutes), the
  window the camera stays open after the last viewer disconnects. It is
  injectable into `CameraStreamer` (`idle_timeout_seconds`) so tests use a
  fraction of a second instead of sleeping 300s.
- `lifespan` no longer opens the camera: it only constructs the streamer.
  Shutdown still calls `stop()` in case a viewer left it running.
- `CameraStreamer.ensure_started()` opens the camera lazily and idempotently on
  the first stream request, cancelling any pending idle-stop; the stream route
  now calls it and turns a camera/model failure into the existing `503` (rather
  than a `500` or a hang). The route's Phase 2 org-binding and role `403`s still
  run *before* `ensure_started`, so an unauthorized or wrong-tenant request
  never triggers a cold start.
- Active viewers are counted by wrapping the shared `mjpeg_stream` generator in
  `CameraStreamer.viewer_stream()`: it increments on generator entry (cancelling
  any pending idle-stop) and decrements in a `finally` on client
  disconnect/shutdown. When the last viewer leaves, an idle countdown is armed;
  a new viewer within the window cancels it and keeps serving from the
  still-open camera.
- The idle-stop is race-safe. A `threading.Timer` cannot be cancelled once it
  has already fired, so its callback re-checks under the lock that it is still
  the current timer and that no viewer arrived - a fresh viewer's
  `ensure_started` that raced the callback can never be stopped out from under
  it, and the camera can never double-start or double-stop. A camera opened but
  never streamed (client disconnects mid cold-start) is also bounded: an idle
  timer is armed whenever no viewer is counted, so an orphaned camera stops on
  its own. `stop()` cancels the timer, joins the thread, and clears it; a prior
  idle-stop's set `stop_event` is re-cleared before a fresh start.
- The latest-frame-wins / non-blocking / capture-never-blocks guarantees are
  untouched: `viewer_stream` delegates framing to the unchanged `mjpeg_stream`,
  and non-stream routes never touch the streamer or its lock.

Finding 2 - a plain, stdlib-installable constraints file (no new tool):

- Added `requirements-lock.txt` at the repo root: `pip freeze --exclude-editable`
  from a clean venv after `pip install -e ".[dev]"`, with a documented header.
  It is a pip *constraints* file, not a replacement for `pyproject.toml`'s
  abstract declarations, so local `pip install -e .` stays flexible.
- CI installs the 3.13 job with `pip install -e ".[dev]" -c requirements-lock.txt`
  for a reproducible pinned build. The 3.10 floor job stays unpinned: the lock's
  `numpy 2.5.x` needs Python 3.11+, so the 3.10 job instead keeps proving the
  abstract lower bounds still resolve.

### Automated verification

- New tests (7):
  - `tests/test_api.py` `LifespanTests` (1): the camera is not started at API
    startup (spy streamer under the real lifespan; neither `start` nor
    `ensure_started` is called on entry).
  - `tests/test_streaming.py` `CameraStreamerLifecycleTests` (6): idle timeout
    defaults to the configured setting; `ensure_started` opens the camera
    lazily and is idempotent while running; the last viewer arms an idle
    countdown (camera not stopped instantly) and the camera then stops after
    the window; a new viewer before the window cancels the pending stop and the
    same camera keeps serving without a restart; an orphaned camera (opened, no
    viewer) stops on its own and reopens cleanly on the next request. All use a
    fake camera thread - no hardware.
- Full Python regression suite (`python -m unittest discover -s tests`, exactly
  as CI runs it): 224 tests passed in 38.7s (217 before this phase; +7).
- Finding 2 dry-run for real, not assumed: created a clean venv, ran
  `pip install -e ".[dev]" -c requirements-lock.txt`, confirmed it installs and
  that the pinned versions (numpy 2.5.1, fastapi 0.139.0, httpx 0.28.1, etc.)
  resolved exactly.
- Real-hardware sanity check of Finding 1 (this machine has a working camera and
  the ONNX models): launched the API with `uvicorn` and confirmed startup
  completes and `/health` serves with **no** camera activity in the log (the old
  eager "live camera stream started" line is gone). Then drove a real
  `CameraStreamer` against the physical camera: `available` is `False` at
  construction, `ensure_started()` actually opens the camera ("Opening camera
  0... Camera ready."), a viewer connect+leave keeps it open with the idle timer
  armed, and after the (shortened) idle window with no viewers the camera is
  auto-released (`available` back to `False`). The browser live-feed visual
  confirmation remains a manual checkpoint, consistent with prior phases.

### Self-review

- Correctness: reviewed, clean. All start/stop/viewer-count/idle-timer
  transitions are serialized under one lock; the fired-timer re-check closes the
  cancel race the finding called out.
- Concurrency: reviewed, clean. The route is a sync endpoint (threadpool), so a
  60-90s cold start blocks only that request's worker, not the event loop or
  other routes; a delayed viewer decrement can only keep the camera open
  *longer* (the safe direction), never cause a stop while a viewer is watching.
- Reuse/simplification: reviewed, clean. Viewer tracking wraps the existing
  `mjpeg_stream` rather than duplicating it; `stop`/`_stop_locked` share one
  teardown; the eager `start()` path is retained unchanged for the CLI proof.
- Security: reviewed, clean for this finding. Org-binding and role `403`s still
  run before any camera work, so a cold start is never triggered by an
  unauthorized or wrong-tenant request.
- Dependencies: no new dependencies. The lock file is generated by stdlib
  `pip freeze`; no `pip-tools`/`poetry`/`uv` introduced.

### Files changed

- `src/face_attendance/config/settings.py`
- `src/face_attendance/api/streaming.py`
- `src/face_attendance/api/main.py`
- `tests/test_api.py`
- `tests/test_streaming.py`
- `requirements-lock.txt`
- `.github/workflows/ci.yml`
- `README.md`
- `CODEX_AUDIT.md`

### Delivery

Implementation commit: pending (see git history)

Push status: pending
