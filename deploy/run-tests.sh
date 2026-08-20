#!/usr/bin/env bash
#
# Runs both test suites unattended. Invoked by job-tracker-tests.timer nightly,
# and worth running by hand after a deploy.
#
# ---------------------------------------------------------------------------
# THE DANGEROUS PART
#
# tests/conftest.py empties every table after each test. That is safe only
# against a throwaway SQLite file. On this server the backend's .env sits in
# the working directory and holds live MariaDB credentials, so a run that
# picked those up would destroy the job search history.
#
# Two independent things prevent that, and neither relies on the other:
#
#   1. This script exports its own DATABASE_URL and never sources the
#      service's .env. DATABASE_URL takes precedence over the DB_* fields
#      that .env supplies.
#
#   2. conftest.py refuses to start unless the engine it actually received is
#      SQLite. That check is on the engine, not on the environment, so it
#      holds even if this script is bypassed or someone runs pytest by hand
#      from the wrong directory.
# ---------------------------------------------------------------------------
set -uo pipefail

BACKEND=/opt/job-tracker-backend
FRONTEND=/opt/job-tracker-frontend
STATUS=/var/lib/job-tracker/test-status

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

export DATABASE_URL="sqlite:///${WORK}/scheduled-tests.sqlite"

started=$(date --iso-8601=seconds)
backend_rc=0
frontend_rc=0

echo "=== backend: pytest ==="
# -o addopts='-q' replaces pytest.ini's addopts wholesale, skipping the HTML
# and coverage reports. Disabling the plugins instead would leave --html in
# addopts and pytest would reject its own arguments.
( cd "$BACKEND" && .venv/bin/python -m pytest -o addopts='-q' ) || backend_rc=$?

echo
echo "=== frontend: vitest ==="
( cd "$FRONTEND" && npx vitest run --reporter=default ) || frontend_rc=$?

if [ "$backend_rc" -eq 0 ] && [ "$frontend_rc" -eq 0 ]; then
    result=PASS
else
    result=FAIL
fi

mkdir -p "$(dirname "$STATUS")"
cat > "$STATUS" <<STATUSEOF
result=$result
started=$started
finished=$(date --iso-8601=seconds)
backend_exit=$backend_rc
frontend_exit=$frontend_rc
STATUSEOF

echo
echo "=== $result (backend=$backend_rc frontend=$frontend_rc) ==="

[ "$result" = PASS ]
