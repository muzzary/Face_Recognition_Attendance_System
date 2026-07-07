# Dependency Strategy

The Khizex specification requires a Python biometric attendance system using computer vision, validation, concurrency, and storage. Phase 1 records those dependency families without installing every heavy application package immediately.

## Required by the Project Brief

- Python 3.10+.
- OpenCV for camera capture and frame processing.
- A face-recognition or embedding library, such as `face_recognition`, InsightFace, or a comparable embedding-based option.
- Pydantic models for data crossing module boundaries.
- Background processing through Python concurrency tools.
- Lightweight storage, with SQLite acceptable.

## Current Decision (final, Phase 4+)

Core runtime dependencies: `pydantic`, `numpy`, `opencv-python`. Nothing else.

- Detection uses **YuNet** (`cv2.FaceDetectorYN`) and embeddings use **SFace** (`cv2.FaceRecognizerSF`) — both ship inside `opencv-python`, so no separate recognition library is needed.
- The previously declared `face_recognition` / InsightFace extras were removed: dlib is painful to build on Windows, and InsightFace pulls in onnxruntime for accuracy this project does not require. SFace is accurate enough for a 1000-employee gallery and keeps installs one-command.
- Model weights are data, not dependencies: two ONNX files fetched by `scripts/download_models.py` with pinned SHA256 hashes.
- Both adapters sit behind local protocols, so a stronger embedding model can be swapped in later without touching the pipeline.

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
