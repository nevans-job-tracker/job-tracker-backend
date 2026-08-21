#!/usr/bin/env bash
#
# Restore rehearsal (KAN-19). Fetches a backup from B2, decrypts it, loads it
# into a scratch database, and checks the result against the live one.
#
# ---------------------------------------------------------------------------
# THIS DELIBERATELY ASKS YOU TO TYPE THE PASSPHRASE
#
# It does NOT read ~/.config/job-tracker/backup.pass, even though that file is
# right there and would make the script non-interactive.
#
# The scenario being rehearsed is that the server is gone. Every off-site
# backup is then unreadable unless the passphrase exists somewhere else. This
# already nearly went wrong once: during KAN-18 the LastPass entry did not
# save, and the passphrase existed only on the machine being backed up. A
# restore that read the server's copy would have passed happily in that state,
# which is worse than not testing at all.
#
# Paste it from the password manager. If that fails, you have found the exact
# problem this rehearsal exists to find.
# ---------------------------------------------------------------------------
set -uo pipefail

BACKEND=/opt/job-tracker-backend
CONF="$HOME/.config/job-tracker"
SCRATCH_DB=job_tracker_restore_check

# Overridable so the status-writing path can be exercised without clobbering
# the real record. Nothing else should set it.
STATUS=${RESTORE_STATUS:-/var/lib/job-tracker/restore-status}

START=$(date +%s)
fail() { echo "ERROR: $*" >&2; write_status FAIL "$*"; exit 1; }

# Until this existed, a rehearsal left nothing behind: it printed to the
# terminal, dropped the scratch database and exited. So "when was this last
# verified, and against which schema?" was answerable only from memory — which
# made the repeat-after-a-migration rule rest on someone remembering it.
#
# `revision` is the field that matters. A rehearsal from three months ago is
# fine if nothing has shipped since; one from yesterday is worthless if a
# migration shipped this morning. Age is not the signal, drift is.
write_status() {
    mkdir -p "$(dirname "$STATUS")" 2>/dev/null
    # `detail` is free text and the MOTD hook sources this file, so it is
    # stripped of anything the shell would act on and then quoted. Left
    # unquoted, every failure message here contains a space, so the hook
    # set detail to the first word and tried to *run* the rest — which for
    # the likeliest failure is the path to backup.env itself.
    #
    # The character set is given in octal on purpose. Written literally it
    # has to survive this file, the shell and tr intact, and a backtick in
    # a bash pattern opens a command substitution — which is exactly the
    # class of mistake this line exists to prevent.
    #   042 "   044 $   047 '   140 `   134 \   012 LF   015 CR
    local detail_clean
    detail_clean=$(printf '%s' "${2:-}" \
        | tr -d '\042\044\047\140\134' | tr '\012\015' '  ')
    cat > "$STATUS" <<STATUSEOF
result=$1
detail="$detail_clean"
finished=$(date --iso-8601=seconds)
elapsed_seconds=$(( $(date +%s) - START ))
artifact=${ARTIFACT:-}
revision=${REVISION:-}
live_revision=${LIVE_REVISION:-}
STATUSEOF
}

ARTIFACT=""; REVISION=""; LIVE_REVISION=""

# --- config ---------------------------------------------------------------
[ -r "$CONF/backup.env" ]  || fail "missing $CONF/backup.env"
[ -r "$CONF/rclone.conf" ] || fail "missing $CONF/rclone.conf"
# shellcheck disable=SC1091
. "$CONF/backup.env"
RCLONE=(rclone --config "$CONF/rclone.conf")
REMOTE="b2:${B2_BUCKET:?}"

# shellcheck disable=SC1091
set -a; . "$BACKEND/.env"; set +a
[ "$SCRATCH_DB" != "${DB_NAME:?}" ] || fail "scratch name collides with the live database"

WORK=$(mktemp -d) || fail "mktemp failed"
chmod 700 "$WORK"
trap 'rm -rf "$WORK"' EXIT

# --- pick the artifact ----------------------------------------------------
ARTIFACT=${1:-}
if [ -z "$ARTIFACT" ]; then
    ARTIFACT=$("${RCLONE[@]}" lsf --files-only "$REMOTE/daily/" | sort | tail -1)
    [ -n "$ARTIFACT" ] || fail "no artifacts in $REMOTE/daily/"
fi
echo "restoring from: daily/$ARTIFACT"

# --- passphrase, from the password manager --------------------------------
read -rsp 'Passphrase (from LastPass, NOT the server file): ' PASSPHRASE; echo
[ -n "$PASSPHRASE" ] || fail "no passphrase given"
printf '%s' "$PASSPHRASE" > "$WORK/pass"
chmod 600 "$WORK/pass"
unset PASSPHRASE

# --- fetch and decrypt ----------------------------------------------------
"${RCLONE[@]}" copyto "$REMOTE/daily/$ARTIFACT" "$WORK/artifact.gpg" \
    || fail "could not download $ARTIFACT from B2"
echo "downloaded $(stat -c%s "$WORK/artifact.gpg") bytes"

if ! gpg --batch --quiet --decrypt --passphrase-file "$WORK/pass" \
        "$WORK/artifact.gpg" 2>"$WORK/gpg.err" | gunzip > "$WORK/dump.sql" 2>/dev/null
then
    echo "--- gpg said ---" >&2; head -3 "$WORK/gpg.err" >&2
    fail "decrypt failed. If the passphrase came from LastPass, THAT is the finding: the off-server copy does not match."
fi
echo "decrypted and decompressed: $(stat -c%s "$WORK/dump.sql") bytes of SQL"

# --- load into a scratch database -----------------------------------------
# Needs privileges the application user does not have, by design: it is scoped
# to its own database. On a real recovery you would have root on a new machine.
echo
echo "Creating scratch database '$SCRATCH_DB' (sudo required)..."
sudo mariadb -e "DROP DATABASE IF EXISTS \`$SCRATCH_DB\`; CREATE DATABASE \`$SCRATCH_DB\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;" \
    || fail "could not create scratch database"
sudo mariadb "$SCRATCH_DB" < "$WORK/dump.sql" || fail "loading the dump failed"
echo "loaded."

# --- verify ---------------------------------------------------------------
q()    { sudo mariadb -N -B "$SCRATCH_DB" -e "$1"; }
live() { sudo mariadb -N -B "$DB_NAME"    -e "$1"; }

echo
printf '%-38s %10s %10s   %s\n' "CHECK" "RESTORED" "LIVE" ""
ok=1
compare() {
    local label=$1 sql=$2 r l
    r=$(q "$sql"); l=$(live "$sql")
    if [ "$r" = "$l" ]; then printf '%-38s %10s %10s   ok\n' "$label" "$r" "$l"
    else printf '%-38s %10s %10s   MISMATCH\n' "$label" "$r" "$l"; ok=0; fi
}

compare "applications"           "SELECT COUNT(*) FROM applications"
compare "contacts"               "SELECT COUNT(*) FROM contacts"
compare "archived applications"  "SELECT COUNT(*) FROM applications WHERE archived_at IS NOT NULL"
compare "applications w/ contact" "SELECT COUNT(DISTINCT application_id) FROM contacts"
REVISION_SQL="SELECT version_num FROM alembic_version"
compare "alembic revision"       "$REVISION_SQL"

# Captured for the status file as well as the table above. This is the field
# the repeat-after-a-migration rule turns on, so it is recorded rather than
# only printed.
REVISION=$(q "$REVISION_SQL")
LIVE_REVISION=$(live "$REVISION_SQL")

# Spot-checks: these exercise archived_at and the foreign key, rather than just
# confirming the tables have the right shape.
echo
echo "archived record (exercises archived_at):"
q "SELECT CONCAT('  id=', id, '  ', company, '  archived_at=', archived_at)
   FROM applications WHERE archived_at IS NOT NULL" || ok=0
echo "record with contacts (exercises the foreign key):"
q "SELECT CONCAT('  id=', a.id, '  ', a.company, '  contact=', c.name, ' <', IFNULL(c.email,'-'), '>')
   FROM applications a JOIN contacts c ON c.application_id = a.id" || ok=0

# --- clean up -------------------------------------------------------------
echo
sudo mariadb -e "DROP DATABASE \`$SCRATCH_DB\`;" && echo "scratch database dropped."

ELAPSED=$(( $(date +%s) - START ))
echo
if [ "$ok" = 1 ]; then
    write_status PASS ""
    echo "=== RESTORE VERIFIED in ${ELAPSED}s ==="
    echo "recorded in $STATUS (revision $REVISION)"
else
    # Left in place until a passing run replaces it. Nothing else clears it,
    # which is deliberate: a rehearsal that did not match is the finding, and
    # it should keep saying so at every login until someone deals with it.
    write_status MISMATCH "restored copy did not match the live database"
    echo "=== RESTORE MISMATCH after ${ELAPSED}s ==="
    exit 1
fi
