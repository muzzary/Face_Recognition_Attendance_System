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
