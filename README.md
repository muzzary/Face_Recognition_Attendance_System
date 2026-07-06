# Face Recognition Attendance System

Python biometric attendance system for the Khizex Python Engineering Internship build challenge.

The system will capture live video, detect faces, extract numeric embeddings, match employees, run multi-frame liveness checks, and log secure clock-in/clock-out events without storing raw face images.

## Current Status

Phase 0 is complete: repository root setup, project navigation docs, starter package layout, and lightweight CI/test scaffolding.

Application implementation has not started yet.

## Project Goals

- Live frame capture through OpenCV.
- Face detection and embedding extraction.
- Employee enrollment using embeddings only.
- Similarity matching with a documented confidence threshold.
- Multi-frame liveness detection to reject static photo or screen spoof attempts.
- Non-blocking capture loop with background recognition work and bounded frame queues.
- Secure attendance logs containing employee ID, timestamp, event type, and confidence score.
- Pydantic validation for data crossing module boundaries.
- Strict type hints and clear modular architecture.

## Setup

Python 3.10+ is expected.

No third-party dependencies are installed yet. Dependencies will be added deliberately in the implementation phases.

## Repository Layout

See [DIRECTORY_MAP.md](DIRECTORY_MAP.md) for the current folder map.

## Project Plan

See [docs/project-plan.md](docs/project-plan.md) for the phase-by-phase build and learning roadmap.

## Verification

Run the starter tests:

```powershell
python -m unittest discover -s tests
```

The CI workflow runs the same test command on push and pull request.

## Security Notes

- Do not commit `.env` files.
- Do not commit raw face images, camera captures, videos, or generated biometric databases.
- The `data/`, `logs/`, and `recordings/` folders are treated as local runtime output.
