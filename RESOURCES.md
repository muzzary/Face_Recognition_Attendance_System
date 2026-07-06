# Face Recognition Attendance System Resources

## Knowledge

- Khizex project specification: local PDF at `D:\Job Hunt\khizex_projects\Khizex_FaceRecognition_Attendance_Detailed.md.pdf`
  Assignment brief. Use for: deliverables, evaluation criteria, security constraints, and phase priorities.
- [OpenCV: Getting Started with Videos](https://docs.opencv.org/4.x/dd/d43/tutorial_py_video_display.html)
  Official OpenCV tutorial for camera capture, frame reads, display loops, and release cleanup. Use for: capture phase.
- [MediaPipe Face Detector for Python](https://developers.google.com/edge/mediapipe/solutions/vision/face_detector/python)
  Official Google AI Edge documentation for face detection in image, video, and live-stream modes. Use for: detection tradeoff research.
- [face_recognition package docs](https://face-recognition.readthedocs.io/en/latest/face_recognition.html)
  API reference for dlib-based face encodings, comparison, and distance helpers. Use for: embedding and matching option research.
- [InsightFace Python package](https://github.com/deepinsight/insightface/tree/master/python-package)
  Official project package area for InsightFace. Use for: embedding-library option research if we choose a deeper model.
- [Pydantic Models](https://docs.pydantic.dev/latest/concepts/models/)
  Official Pydantic model documentation. Use for: boundary validation and typed data contracts.
- [Python concurrent.futures](https://docs.python.org/3/library/concurrent.futures.html)
  Official Python executor documentation. Use for: background recognition workers and process/thread tradeoffs.
- [Python sqlite3](https://docs.python.org/3/library/sqlite3.html)
  Official standard-library SQLite documentation. Use for: local employee and attendance storage.
- [Python Packaging User Guide: Writing your pyproject.toml](https://packaging.python.org/en/latest/guides/writing-pyproject-toml/)
  Official packaging guide for build metadata and project configuration. Use for: Phase 1 project setup.
- [Setuptools: Package Discovery and Namespace Packages](https://setuptools.pypa.io/en/latest/userguide/package_discovery.html)
  Official setuptools guide for package discovery, including `src` layout projects. Use for: editable install and package discovery.
- [Python unittest](https://docs.python.org/3/library/unittest.html)
  Official Python standard-library testing documentation. Use for: dependency-free test discovery and assertions.

## Wisdom (Communities)

- [OpenCV Forum](https://forum.opencv.org/)
  Use for: camera capture, frame-rate, and platform-specific OpenCV issues.
- [Python Discuss](https://discuss.python.org/)
  Use for: Python packaging, concurrency, and standard-library questions.
- [Stack Overflow: OpenCV](https://stackoverflow.com/questions/tagged/opencv)
  Use for: specific implementation errors after reading official docs first.

## Gaps

- A final face-recognition library choice is not locked yet. Compare installation difficulty, Windows support, embedding quality, and demo reliability before adding dependencies.
- Liveness approach needs a primary technical reference once we choose blink, micro-movement, texture, or a combination.
