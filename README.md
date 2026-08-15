# Job Tracker — Backend (FastAPI)

REST API for tracking job applications. Talks to a MySQL database.

## 1. Local setup

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

Tables are created automatically on first app startup (via `Base.metadata.create_all`).
No manual migration needed for the initial version.

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

## API overview

- `GET /applications` — list, with `search`, `status`, `sort_by`, `sort_dir`, `skip`, `limit` query params
- `GET /applications/{id}` — get one
- `POST /applications` — create
- `PATCH /applications/{id}` — partial update
- `DELETE /applications/{id}` — delete
- `GET /health` — health check
