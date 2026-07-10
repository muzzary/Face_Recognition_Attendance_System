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
