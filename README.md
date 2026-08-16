# Job Tracker — Backend (FastAPI)

REST API for tracking job applications. Talks to a MySQL database.

## 1. Local setup

**Requires Python 3.10–3.12.** `pydantic==2.9.2` has no prebuilt wheel for
Python 3.14, and `pydantic-core` fails to build from source, so `pip install`
dies partway through. 3.13 is untested — it sits outside the pinned range, so
treat it as unsupported until someone verifies it. Check what you have before
creating the venv:

```bash
python3 --version
```

If the default is too new, point the venv at a specific interpreter
(`python3.12 -m venv venv`, or `py -3.12 -m venv venv` on Windows). Then:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# edit .env with your MySQL credentials
```

## 2. Create the MySQL database and user

```sql
CREATE DATABASE job_tracker CHARACTER SET utf8mb4;
CREATE USER 'job_tracker'@'localhost' IDENTIFIED BY 'changeme';
GRANT ALL PRIVILEGES ON job_tracker.* TO 'job_tracker'@'localhost';
FLUSH PRIVILEGES;
```

Tables are still created on first app startup via `Base.metadata.create_all`, so
an empty database needs nothing further to get going.

Alembic is now set up alongside it (§7) but is **not** yet wired into startup —
that swap is KAN-16. Until then both mechanisms exist and `create_all` is the
one that actually runs.

## 3. Run it (dev)

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Interactive API docs: http://localhost:8000/docs

## 4. Deploy on your Linux machine (systemd)

Assuming the repo lives at `/opt/job-tracker-backend`:

```bash
cd /opt/job-tracker-backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in real values
```

The Python 3.10–3.12 requirement from §1 applies here too, and the server's
default `python3` is whatever its distribution ships — check it rather than
assuming, since the failure surfaces as a confusing build error deep in
`pip install` rather than a clear version complaint.

Create `/etc/systemd/system/job-tracker-backend.service`:

```ini
[Unit]
Description=Job Tracker FastAPI backend
After=network.target mysql.service

[Service]
User=youruser
WorkingDirectory=/opt/job-tracker-backend
EnvironmentFile=/opt/job-tracker-backend/.env
ExecStart=/opt/job-tracker-backend/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

Then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now job-tracker-backend
sudo systemctl status job-tracker-backend
```

## 5. CORS

Update `CORS_ORIGINS` in `.env` to match wherever the frontend is served from
(e.g. `http://localhost:5173` for dev, or `http://<your-lan-ip>` once you
build and serve the frontend).

## 6. Tests

```bash
pip install -r requirements-dev.txt
pytest
```

The suite runs against a throwaway SQLite file, so **no MySQL is required** —
`tests/conftest.py` sets `DATABASE_URL` before the app is imported, and each
test starts from empty tables.

> **The tests delete data.** Every table is emptied after each test. This is
> safe only because `DATABASE_URL` points at throwaway SQLite. Never run the
> suite with an environment that points at the real database — in particular,
> a scheduled or deploy-time run must set its own `DATABASE_URL` rather than
> inheriting the service's `.env`.

Every run writes two browsable reports:

- `htmlcov/index.html` — line-by-line coverage (currently 99%)
- `report.html` — which tests ran and passed

Both are generated output, and both are gitignored. Skip them with:

```bash
pytest -o addopts='-q'
```

That replaces the `addopts` block in `pytest.ini` wholesale, which is what
makes it work. Disabling the plugins instead — `pytest --no-cov -p no:html` —
looks right but fails: `-p no:html` removes the code that understands
`--html`, while `addopts` still supplies it, so pytest rejects its own
configured arguments with `unrecognized arguments` and runs nothing.

The suite needs the same Python 3.10–3.12 interpreter as the app — see §1.

## 7. Migrations

Alembic manages schema changes. The baseline revision matches the models as of
its creation; every schema change after that gets its own revision.

```bash
alembic current                              # what the database is at
alembic upgrade head                         # apply everything outstanding
alembic revision --autogenerate -m "message" # draft a revision from model changes
alembic downgrade -1                         # step back one
```

**`alembic.ini` deliberately has no `sqlalchemy.url`.** `alembic/env.py` takes
it from the app's own `Settings`, so connection details have one source of
truth and no password sits in a committed file. It also means Alembic honours
the same `DATABASE_URL` override the tests use — to run migrations against a
throwaway SQLite file rather than the real database, set it:

```bash
DATABASE_URL=sqlite:///./scratch.sqlite alembic upgrade head
```

**Always read what `--autogenerate` produced before committing it.** It drafts,
it does not decide. Two things in particular:

- It only sees what SQLAlchemy models declare. Anything applied to the database
  by hand is invisible to it, and it will happily propose dropping it.
- It renders against whichever dialect it connected to. Generating on SQLite
  and deploying to MySQL leaks SQLite spellings into the migration — that is
  exactly what happened to the baseline, where `func.now()` came out as the
  literal `(CURRENT_TIMESTAMP)`. Prefer generating against a database of the
  same engine you deploy to.

Not yet done, tracked in KAN-16: startup still calls `Base.metadata.create_all`,
so two mechanisms currently define the schema. Until that story lands, treat
`create_all` as the one in force.

## API overview

- `GET /applications` — list, with `search`, `status`, `show`, `sort_by`, `sort_dir`, `skip`, `limit` query params. `show` is `active` (default), `archived`, or `all`, and applies independently of `status`
- `GET /applications/{id}` — get one, including its contacts
- `POST /applications` — create
- `PATCH /applications/{id}` — partial update
- `POST /applications/{id}/archive` — archive (hide from the default list)
- `POST /applications/{id}/unarchive` — restore
- `GET /applications/{id}/contacts` — list contacts
- `POST /applications/{id}/contacts` — add a contact
- `PATCH /applications/{id}/contacts/{contact_id}` — partial update
- `DELETE /applications/{id}/contacts/{contact_id}` — delete
- `GET /health` — health check

Contact lookups are scoped by `application_id`, so a contact cannot be read or
modified through another application's URL.

**There is no delete route for applications, by design.** They are archived
rather than deleted, and never purged. Contacts *can* be deleted outright —
a contact is a detail of an application, not history worth keeping.

## Configuration

`DATABASE_URL` overrides the `DB_*` parts with a full SQLAlchemy URL when set.
The test suite uses it; deployment can too.
