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

