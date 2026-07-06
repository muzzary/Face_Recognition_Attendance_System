# Face Recognition Attendance System

Python biometric attendance system for the Khizex Python Engineering Internship build challenge.

The system will capture live video, detect faces, extract numeric embeddings, match employees, run multi-frame liveness checks, and log secure clock-in/clock-out events without storing raw face images.

## Current Status

Phase 2 is complete: core Pydantic data contracts are in place for the attendance pipeline boundaries.

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

Create and activate a virtual environment:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Install this project in editable mode:

```powershell
python -m pip install -e .
```

No application dependencies are installed by default yet. The PDF-required dependency families are declared as optional extras and will be installed deliberately in the matching implementation phases.

## Dependency Decision

Current dependency decision:
- Use the Python standard library `unittest` for now.
- Use setuptools only as the packaging build backend.
- Keep the default install dependency-light.
- Install Pydantic as a core runtime dependency for boundary models.
- Declare heavier vision/recognition dependency families as optional extras in `pyproject.toml`.

Planned installs:
- Phase 4 or 5: `python -m pip install -e .[vision]` for OpenCV and NumPy.
- Phase 6: choose `face_recognition`, InsightFace, or a comparable embedding library.

See [docs/dependency-strategy.md](docs/dependency-strategy.md) for the full reasoning.

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
