# Face Attendance Frontend

A React + TypeScript + Vite single-page app with role-appropriate dashboards
over the FastAPI backend. You sign in, and the view is chosen from the JWT
`role` claim (decoded client-side purely for UX branching - the API enforces the
real authorization):

- **Admin / manager** (identical scope): the full employee roster with
  active/inactive status, plus an org-wide attendance report with a
  filter-by-employee dropdown.
- **Employee** (self-service): only their own attendance history plus simple
  derived stats (days present, last clock-in/out) - the roster route is never
  called for this role (the API 403s it).

Styling is a single plain stylesheet (`src/App.css`) - no UI kit, no extra
dependencies.

## Prerequisites

The FastAPI backend must be running locally on port 8000 with a seeded database.
From the repo root:

```powershell
face-attendance init-db            # create the schema
python scripts/seed_dev_data.py    # seed the "acme" org used by this app
uvicorn face_attendance.api.main:app --reload   # serves http://127.0.0.1:8000
```

The org id is hardcoded to `acme` at the top of `src/App.tsx` (matching the seed
script). CORS for `http://localhost:5173` is already enabled on the API. The API
also needs `FA_JWT_SECRET` set to issue/verify tokens.

Sign in with the seeded dev logins (all password `devpassword123`) to see each
view:

| Login              | Role     | View                                |
| ------------------ | -------- | ----------------------------------- |
| `admin@acme.test`  | admin    | roster + org-wide attendance report |
| `manager@acme.test`| manager  | same full-org view as admin         |
| `employee@acme.test`| employee| own attendance + personal stats     |

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
