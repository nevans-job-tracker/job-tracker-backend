# job-tracker-backend — Project Context

FastAPI REST API for the Job Tracker app. This file covers **backend-specific**
decisions only.

## Shared documentation

Project-wide architecture and functional requirements live in the
`job-tracker-docs` repo, included here as a submodule at `docs/`:

@docs/ARCHITECTURE.md
@docs/REQUIREMENTS.md

`REQUIREMENTS.md` is the authority where it overlaps with anything else.

**Do not edit files under `docs/` from this repo** — it is a detached-HEAD
snapshot of another repo, so edits made here are easy to lose. Edit them in
`job-tracker-docs`, then bump the pointer:

```bash
git submodule update --remote docs && git commit -am "Bump docs" && git push
```

If `docs/` is empty after cloning, run `git submodule update --init`.

## Backend design choices

- SQLAlchemy ORM. Two tables: `applications`, and `contacts` related many-to-one
  to it. Contacts are managed through endpoints nested under their application
  and scoped by `application_id`.
- Tables auto-created on startup via `Base.metadata.create_all` — no migration
  tool set up yet. Adequate while the database does not yet exist; Alembic is
  worth adding before the first schema change *after* real data exists (KAN-10).
- CORS origins configured via `.env` (`CORS_ORIGINS`) so the frontend's
  deployed origin must be added explicitly.
- Status field is an enum: applied, phone_screen, interview, offer,
  rejected, ghosted, withdrawn.
- **Status transitions are deliberately unvalidated** — any status may be set at
  any time. This is a decision, not an oversight; see `REQUIREMENTS.md` §3.
- **Records are archived, never deleted.** An `archived_at` timestamp marks
  archived rows; nothing is ever purged, and there is deliberately no DELETE
  route for applications. Contacts *can* be deleted outright.

## Testing

```bash
pytest        # 109 tests, 99% statements
```

Runs against throwaway SQLite via a `DATABASE_URL` override, so no MySQL is
needed. **It empties every table** — never point it at real data.
`pydantic==2.9.2` has no wheel for Python 3.14; use 3.10–3.12.
