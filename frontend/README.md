# Face Attendance Frontend (Phase 4 skeleton)

A thin React + TypeScript + Vite single-page app that reads the roster and
recent attendance from the FastAPI backend and renders them as plain HTML
tables. No auth, no styling, no routing yet - this is a walking skeleton proving
browser -> API -> SQLite works end to end.

## Prerequisites

The FastAPI backend must be running locally on port 8000 with a seeded database.
From the repo root:

```powershell
face-attendance init-db            # create the schema
python scripts/seed_dev_data.py    # seed the "acme" org used by this app
uvicorn face_attendance.api.main:app --reload   # serves http://127.0.0.1:8000
```

The org id is hardcoded to `acme` at the top of `src/App.tsx` (matching the seed
script). CORS for `http://localhost:5173` is already enabled on the API.

## Install and run

```powershell
cd frontend
npm install
npm run dev        # Vite dev server on http://localhost:5173
```

## Other commands

```powershell
npm run build      # type-check + production build
npm test           # Vitest component tests (mocked fetch)
```
