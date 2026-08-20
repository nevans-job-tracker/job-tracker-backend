# Job Tracker — Backend (FastAPI)

REST API for tracking job applications. Talks to MariaDB over the MySQL wire
protocol (`mysql+pymysql://`). Oracle MySQL works equally well — nothing here
is specific to either.

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
# edit .env with your database credentials
```

## 2. Create the database and user

The deployed server runs **MariaDB** from Debian's own archive (KAN-22). On
Debian the root account authenticates over the unix socket, so `sudo mariadb`
gets you a prompt with no password to manage.

```sql
CREATE DATABASE job_tracker CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'job_tracker'@'localhost' IDENTIFIED BY 'changeme';
GRANT ALL PRIVILEGES ON job_tracker.* TO 'job_tracker'@'localhost';
FLUSH PRIVILEGES;
```

Grant on `job_tracker.*`, never `*.*` — the application user has no business
outside its own database. Generate the password on the machine
(`openssl rand -base64 32 | tr -dc 'A-Za-z0-9' | head -c 28`) and keep it
alphanumeric: the SQLAlchemy URL is assembled by string interpolation, so a
`@` or `/` in the password corrupts it.

Then build the schema by migrating:

```bash
alembic upgrade head
```

**The app does not create tables.** It has no `create_all` call, so starting it
against a database that has not been migrated fails on the first query that
touches a table — `no such table: applications`, or the server's equivalent. That
is deliberate: one mechanism owns the schema. See §7.

Note that `/health` still answers `200` on an un-migrated database, since it
touches nothing. A passing health check is not evidence the schema is there.

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
alembic upgrade head   # required — the app will not create tables
```

The Python 3.10–3.12 requirement from §1 applies here too, and the server's
default `python3` is whatever its distribution ships — check it rather than
assuming, since the failure surfaces as a confusing build error deep in
`pip install` rather than a clear version complaint.

**`alembic upgrade head` has to run on every deploy that carries a new
revision, before the service restarts.** The app no longer creates or alters
schema, so a deploy that skips it starts a service whose queries fail against a
schema behind its code. That is no longer a command to remember — the unit
below runs it as `ExecStartPre` on every start.

The unit is committed at [`deploy/job-tracker-backend.service`](deploy/job-tracker-backend.service)
rather than reproduced here, so it lives under version control where a change
to it shows up in a diff:

```bash
sudo cp deploy/job-tracker-backend.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now job-tracker-backend
```

Three things in it are load-bearing:

- **`ExecStartPre=... alembic upgrade head`** runs migrations before every
  start, so a deploy carrying a new revision cannot bring the service up
  against a schema that is behind its code. It is idempotent.
- **`User=jobtracker`** — a system account with no shell and no login, which
  owns nothing. The tree is owned by your login user with the directory setgid,
  so the service reads everything and can write nothing.
- **`ProtectSystem=strict`** with no `ReadWritePaths` exception.

**`--host 127.0.0.1`, not `0.0.0.0`.** nginx is the only thing that talks to
this service, and it does so over loopback (KAN-20). Binding to all interfaces
would publish the API — and `/docs` — directly on the LAN as a second reachable
door, which is precisely the surface §6.1 says must be closed before this app
is exposed anywhere wider.

## 5. CORS

**The deployed setup does not use CORS.** nginx serves the frontend and proxies
`/api/` to this service on the same origin (KAN-20), so the browser never makes
a cross-origin request and `CORS_ORIGINS` is never consulted.

It still matters in **development**, where Vite serves on `:5173` and this API
answers on `:8000` — two different origins. The default
(`http://localhost:5173`) already covers that, so nothing needs changing for a
normal dev setup.

Worth knowing if you ever call this API from somewhere other than the app:
a `CORS_ORIGINS` mismatch fails *only in the browser*. `curl` will work
perfectly against the same endpoint, which makes it a confusing thing to
diagnose from the symptoms alone.

## 6. Tests

```bash
pip install -r requirements-dev.txt
pytest
```

The suite runs against a throwaway SQLite file, so **no database server is
required** —
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
  and deploying to MariaDB leaks SQLite spellings into the migration — that is
  exactly what happened to the baseline, where `func.now()` came out as the
  literal `(CURRENT_TIMESTAMP)`. It was corrected by hand and later verified
  against the real server, where it renders as `current_timestamp()` and
  autogenerate reports no drift. Prefer generating against the same engine you
  deploy to.

### The test suite migrates too

`tests/conftest.py` builds its schema with `alembic upgrade head`, not
`create_all`. `create_all` would be marginally faster — measured at about
0.1s across the whole suite — but it builds the schema from the models, so it
would pass whether or not the migrations actually work, leaving the one
mechanism that runs in production untested.

Teardown runs `downgrade base`, which exercises the downgrade path that would
otherwise never run at all.

The consequence worth knowing: **a broken revision now fails the test suite**,
which is the point. If the suite starts failing at session setup rather than in
a test, look at the newest revision first.

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
