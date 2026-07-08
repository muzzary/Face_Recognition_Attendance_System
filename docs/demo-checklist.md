# Demo Checklist

Rehearsal script proving the rubric items: recognition, secure logging, multi-face handling, smooth video, and spoof rejection. Run from a clean terminal in the repo root with the virtual environment active.

## 0. Preconditions

- [ ] `python scripts/download_models.py` reports both models `verified`
- [ ] `face-attendance init-db` prints the database path
- [ ] `python -m unittest discover -s tests` is green
- [ ] On a new terminal/camera: `face-attendance calibrate-liveness --duration 20` and apply any recommended `FA_LIVENESS_*` overrides before proceeding

## 1. Enrollment (embeddings only, no images)

- [ ] `face-attendance enroll --employee-id EMP-001 --name "Your Name"` captures 5 samples with quality feedback
- [ ] `face-attendance employees list` shows EMP-001 active
- [ ] Prove no images stored: `data/` contains only the SQLite file; the schema has no image/raw columns (covered by tests; optionally open the DB and show `face_embeddings.vector_json` is numbers)

## 2. Recognition and attendance logging

- [ ] `face-attendance attend` opens the video window and stays smooth while recognizing
- [ ] Your face gets a box + employee id + confidence overlay
- [ ] After the liveness window (~1 s), console prints `CLOCK_IN: EMP-001 ...` exactly once (cooldown suppresses repeats)
- [ ] `face-attendance report` shows the event with employee ID, timestamp, event type, confidence, and distance
- [ ] Stand in frame past the cooldown: next log is `CLOCK_OUT` (toggle works)

## 3. Multi-face handling

- [ ] Two people (or one person + an unknown) in frame: both get boxes; the unknown is labeled `unknown` and never logged

## 4. Unknown face rejection

- [ ] A non-enrolled person alone in frame produces no attendance events (`face-attendance report` unchanged)

## 5. Spoof rejection (record results in this file)

- [ ] Printed/phone photo held STILL at the camera: box appears, but liveness fails (`static photo` reason in messages); no event logged. Result: ____
- [ ] Photo WAVED/moved by hand: liveness fails (`rigid` reason); no event logged. Result: ____
- [ ] Known limitation to state honestly if asked: a video replay on a screen is not caught by micro-movement liveness (documented in README).

## 6. Resilience

- [ ] Unplug/cover the camera mid-session: clean `camera failure` message and session summary, no crash
- [ ] Session summary prints frames read / processed / dropped stale / events logged
- [ ] `q` quits the window cleanly; camera is released (relaunch works immediately)

## 7. Scale story (talking points)

- Matching is one numpy matrix product over all employees (tested at 1000 x 3 embeddings)
- SQLite WAL + indexes on the event/embedding hot paths
- Stale-frame dropping keeps video smooth regardless of recognition speed
