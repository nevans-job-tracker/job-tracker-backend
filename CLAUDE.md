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
- **Alembic owns the schema outright.** The `Base.metadata.create_all` call is
  gone (KAN-16) — `alembic upgrade head` is the only way tables come into
  existence, and the systemd unit's `ExecStartPre` runs it on every start.
  Starting against an un-migrated database fails on the first query that
  touches a table, deliberately.
- CORS origins configured via `.env` (`CORS_ORIGINS`) so the frontend's
  deployed origin must be added explicitly.
- Status field is an enum: applied, phone_screen, interview, offer, rejected,
  ghosted, withdrawn, interested. `interested` is last because MariaDB stores an
  ENUM as its ordinal and appending is the only change that leaves existing rows
  alone — the frontend shows it first. See `REQUIREMENTS.md` §3.
- **`date_applied` is nullable** (KAN-31): a job can be tracked before it is
  applied for. A create with no date and no stated status is stored as
  `interested` rather than `applied`.
- **`company_size` is an enum of Wellfound's six bands**, declared smallest to
  largest. That order is load-bearing: MariaDB stores an ENUM as its ordinal,
  so it is what makes sorting by the column mean band order. Note this also
  means enum columns sort differently under SQLite, which is what the tests
  run on — see `REQUIREMENTS.md` §4.2.
- **`years_experience_min` is a nullable smallint**, minimum only. `0` is a
  real answer (entry level) and distinct from NULL; negatives are rejected.
- **A NULL sorts as though it were greater than every real value** in
  `crud.list_applications`, so the default date-descending view leads with jobs
  not yet applied to. Written as a leading `IS NULL` key because MariaDB has no
  `NULLS FIRST` / `NULLS LAST`. See `REQUIREMENTS.md` §4.2.
- **Status transitions are deliberately unvalidated** — any status may be set at
  any time. This is a decision, not an oversight; see `REQUIREMENTS.md` §3.
- **Records are archived, never deleted.** An `archived_at` timestamp marks
  archived rows; nothing is ever purged, and there is deliberately no DELETE
  route for applications. Contacts *can* be deleted outright.

## Testing

```bash
pytest        # 135 tests, 99% statements
```

Runs against throwaway SQLite via a `DATABASE_URL` override, so no MySQL is
needed. **It empties every table** — never point it at real data.
`pydantic==2.9.2` has no wheel for Python 3.14; use 3.10–3.12.
