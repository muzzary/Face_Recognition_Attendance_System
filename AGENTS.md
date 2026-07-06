# AGENTS.md

This project follows the user's engineering workflow for a Windows laptop.

## Navigation

Start with [DIRECTORY_MAP.md](DIRECTORY_MAP.md) before editing. Keep it updated whenever files or folders are added, removed, or repurposed.

## Workflow

- Plan before coding: identify scope, risks, resources, and likely failure points.
- Build phase by phase. Finish, verify, review, and log each phase before starting the next.
- Add or update automated tests at the end of each phase.
- Keep [docs/phase-log.md](docs/phase-log.md) updated with what changed and how it was verified.
- Wait for the user's manual test OK before moving into the next implementation phase when behavior needs hands-on confirmation.

## Project Requirements

- Build a Python 3.10+ face-recognition attendance system.
- Keep the pipeline modular: capture, detection, embeddings, matching, liveness, storage, logging, and config stay separated.
- Implement live video capture, face detection, embedding extraction, employee matching, and clock-in/clock-out logging.
- Include an employee enrollment flow that stores numeric embeddings only.
- Handle multiple faces in one frame gracefully.
- Implement real multi-frame liveness detection, such as blink tracking, micro-movement checks, or texture analysis.
- Reject static photo or phone/screen spoof attempts and document the test result.
- Keep the video capture/display loop smooth by running expensive recognition work in a background thread, process, or executor.
- Prevent frame backlog with a bounded queue or stale-frame dropping strategy.
- Store attendance logs with employee ID, timestamp, event type, and confidence score.
- Document the chosen matching threshold, liveness limitations, and concurrency design in the README.

## Implementation Instructions

- Use Pydantic models for data crossing module boundaries once dependencies are introduced.
- Use SQLite unless a later phase has a clear reason to choose another database.
- Keep raw camera frames in memory only; never write raw face images or demo captures into tracked files.
- Make errors explicit around camera disconnects, corrupted frames, failed matches, database writes, and background workers.
- Prefer small automated tests for each phase, including regression checks for earlier behavior.
- Do not add a third-party dependency without discussing it first.

## Code Quality

- Use clear, modular Python with strict type hints.
- Prefer small, explicit modules over large scripts.
- Add comments only for non-obvious decisions and important tradeoffs.
- Keep dependencies minimal and ask before adding a new third-party package.
- Use defensive error handling around cameras, files, databases, external calls, and concurrency boundaries.

## Security Rules

- Never commit secrets. Use `.env` for local secrets and keep it ignored.
- Never store raw face images in the repo, database, logs, or runtime outputs.
- Store biometric data only as numeric embeddings.
- Validate cross-boundary data with Pydantic once project dependencies are introduced.

## Git

- Use simple, plain commit messages.
- Do not add Codex attribution to commits.
- Commit after each completed phase. Push when a remote is configured and available.
