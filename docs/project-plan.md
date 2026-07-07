# Project Plan

This plan turns the Khizex assignment into small build-and-learn phases. Each phase ends with automated tests, a phase-log entry, self-review, commit, push, and a user manual test checkpoint when the behavior touches the camera or live app flow.

## Phase 0 - Root Setup

Status: complete.

Build outcome:
- Git repo, README, AGENTS instructions, directory map, phase log, CI, starter source folders, and starter structure tests.

Learn:
- Why project roots matter: fast navigation, rollback safety, CI as a small regression net, and docs that keep future work grounded.

Verification:
- `python -m unittest discover -s tests`

## Phase 1 - Tooling and Dependency Decision

Status: complete.

Build outcome:
- Create the Python project configuration.
- Record the project-required dependency families: OpenCV, Pydantic, and a face-recognition or embedding library.
- Declare those families as optional extras so default install stays light until the matching phase.
- Choose `unittest` for now and keep pytest out until it earns its place.
- Add lint/type commands only if the selected tooling stays lightweight.

Learn:
- Python project anatomy: package layout, dependency files, virtual environments, and why lockfiles matter.

Tests:
- Verify imports, package discovery, and CI commands.
- Keep dependency installation reproducible.

Manual checkpoint:
- User confirms local environment can run the baseline test command.

## Phase 2 - Core Data Contracts

Status: complete.

Build outcome:
- Add Pydantic models for frame metadata, face boxes, embeddings, employee records, match results, liveness results, and attendance events.
- Define event types and confidence/threshold fields.

Learn:
- Boundary models: why validation belongs at module edges, not randomly inside business logic.

Tests:
- Valid payloads are accepted.
- Malformed/corrupted payloads fail loudly with clear errors.

## Phase 3 - Storage Foundation

Status: complete.

Build outcome:
- Add SQLite schema and repository functions for employees, embeddings, and attendance logs.
- Store embeddings as numeric data only.
- Add safe database initialization and error handling.

Learn:
- Persistence boundaries: schema design, transactions, and separating storage code from recognition logic.

Tests:
- Create database in a temporary path.
- Insert/read employees and attendance logs.
- Prove raw image paths or bytes are not part of the schema.

## Phase 4 - Camera Capture

Status: complete.

Build outcome:
- Add OpenCV camera capture module.
- Read frames with metadata.
- Handle camera open/read failure explicitly.
- Keep raw frames in memory only.

Learn:
- Video loops: frame reads, timestamps, cleanup, and why camera resources must be released.

Tests:
- Unit-test capture error handling with fakes.
- Keep real webcam behavior as a manual test.

Manual checkpoint:
- User confirms webcam opens, displays or reads frames, and exits cleanly.

## Phase 5 - Face Detection

Status: complete.

Build outcome:
- Add face detector adapter behind a local interface.
- Return one result per detected face.
- Handle zero, one, and multiple faces.

Learn:
- Adapter pattern: how to isolate third-party computer-vision libraries so the rest of the app stays testable.

Tests:
- Fake detector returns multiple face boxes.
- Invalid frames and detector failures produce clear errors.

Manual checkpoint:
- User confirms face boxes appear on webcam frames or sample frames.

## Phase 6 - Embeddings and Enrollment

Status: complete.

Build outcome:
- Extract embeddings for detected faces.
- Add employee enrollment flow.
- Store only embeddings and employee metadata, never raw images.

Learn:
- Embeddings: how face images become numeric vectors and why distance scores are not identity by themselves.

Tests:
- Enrollment stores embeddings.
- Empty or bad detections are rejected.
- No raw image data is written to storage.

Manual checkpoint:
- User enrolls one test employee locally.

## Phase 7 - Matching and Attendance Logging

Status: complete (includes storage scale upgrade: WAL mode and indexes).

Build outcome:
- Compare live embeddings against enrolled employee embeddings.
- Define and document the first matching threshold.
- Log clock-in/clock-out events with employee ID, timestamp, event type, and confidence score.

Learn:
- Threshold thinking: false accepts, false rejects, and why a score needs context.

Tests:
- Known vectors match below/above threshold as expected.
- Attendance events are written with the required fields.
- Unknown faces do not create attendance logs.

Manual checkpoint:
- User confirms a recognized employee creates a log entry.

## Phase 8 - Multi-Frame Liveness

Status: complete (micro-movement + non-rigidity; manual spoof test pending user checkpoint).

Build outcome:
- Implement the chosen liveness approach, likely blink tracking or micro-movement first.
- Require liveness confirmation before attendance logging.
- Document limitations honestly.

Learn:
- Anti-spoofing basics: why a single image heuristic is weak and why multi-frame evidence is stronger.

Tests:
- Synthetic frame/landmark sequences pass or fail liveness rules.
- Static sequences are rejected.

Manual checkpoint:
- User tests a live face and a photo/screen spoof attempt.

## Phase 9 - Non-Blocking Background Processing

Status: complete.

Build outcome:
- Move expensive recognition work off the capture loop.
- Use a bounded queue or latest-frame strategy.
- Drop stale frames when recognition cannot keep up.
- Add graceful worker shutdown.

Learn:
- Concurrency for real-time apps: producer/consumer flow, backpressure, queues, workers, and shutdown.

Tests:
- Queue never grows unbounded.
- Stale frames are dropped.
- Worker errors are surfaced clearly.

Manual checkpoint:
- User confirms the live feed stays smooth during recognition.

## Phase 10 - End-to-End App Flow

Status: complete.

Build outcome:
- Add a simple CLI or app entrypoint for enrollment and attendance mode.
- Connect capture, detection, embeddings, matching, liveness, storage, and logging.
- Add clear operator messages.

Learn:
- Integration thinking: small tested modules become one reliable workflow through explicit boundaries.

Tests:
- End-to-end flow with fakes.
- CLI argument validation.
- Failure paths for missing camera, empty database, and storage errors.

Manual checkpoint:
- User runs enrollment and attendance mode locally.

## Phase 11 - Hardening and Documentation

Status: complete.

Build outcome:
- Tighten error handling, logging, README instructions, and security notes.
- Add liveness limitations, concurrency explanation, backlog strategy, threshold rationale, and demo instructions.

Learn:
- Engineering review readiness: explaining not just what works, but what can fail and why.

Tests:
- Full automated suite.
- README commands are checked manually.

Manual checkpoint:
- User follows README from a clean environment.

## Phase 12 - Demo and Submission Polish

Build outcome:
- Prepare demo checklist for recognition, logging, and spoof rejection.
- Confirm CI is green.
- Tag or mark the submission-ready commit if desired.

Learn:
- Demo discipline: show the evaluator exactly what the rubric asks for, with proof and limits.

Tests:
- Full automated suite.
- Manual demo rehearsal.

Manual checkpoint:
- User approves final demo and submission package.

## Teaching Rhythm Per Phase

Before coding each phase:
- Create or open a short lesson in `lessons/` for the main concept.
- Add or update a quick reference in `reference/` when the concept will be reused.
- Ask one retrieval question before moving to implementation.

During coding:
- Connect each implementation choice back to the lesson.
- Keep examples tiny and directly tied to the current phase.

After verification:
- Record any demonstrated understanding in `learning-records/`.
- Update `docs/phase-log.md`.
