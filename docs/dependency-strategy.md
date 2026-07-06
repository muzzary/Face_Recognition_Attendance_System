# Dependency Strategy

The Khizex specification requires a Python biometric attendance system using computer vision, validation, concurrency, and storage. Phase 1 records those dependency families without installing every heavy application package immediately.

## Required by the Project Brief

- Python 3.10+.
- OpenCV for camera capture and frame processing.
- A face-recognition or embedding library, such as `face_recognition`, InsightFace, or a comparable embedding-based option.
- Pydantic models for data crossing module boundaries.
- Background processing through Python concurrency tools.
- Lightweight storage, with SQLite acceptable.

## Current Phase 1 Decision

- Runtime dependencies remain empty in the default install: `python -m pip install -e .`.
- PDF-required dependency families are declared as optional extras in `pyproject.toml`.
- We will install each optional extra when the matching implementation phase begins.

## Why Not Install Everything Now?

- OpenCV and face-recognition packages can be heavy on Windows.
- `face_recognition` depends on dlib, which can be difficult to install.
- InsightFace may require ONNX runtime choices that should match the machine and demo needs.
- Installing only what a phase needs keeps failures easier to diagnose.

## Planned Installs by Phase

- Phase 2: install `.[validation]` for Pydantic boundary models.
- Phase 4 or 5: install `.[vision]` for OpenCV and NumPy.
- Phase 6: choose and install either `.[recognition-face-recognition]`, `.[recognition-insightface]`, or a better documented equivalent.

## Standard Library Pieces

- Concurrency: `threading`, `queue`, `multiprocessing`, `asyncio`, or `concurrent.futures`.
- Storage baseline: `sqlite3`.
- Tests for now: `unittest`.

## Decision Rule

Before adding a dependency to the default runtime install, confirm:

- It is needed for the current phase.
- It works on this Windows machine.
- It has a clear role in the architecture.
- It does not cause raw biometric files to be stored.

