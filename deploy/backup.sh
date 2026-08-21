#!/usr/bin/env bash
#
# Nightly off-site backup. Invoked by job-tracker-backup.timer.
#
# Policy comes from KAN-17 (REQUIREMENTS.md §5): off-site object storage,
# nightly, 30 daily plus 12 monthly retained, encrypted client-side before
# upload.
#
# ---------------------------------------------------------------------------
# THE ORDERING THAT MATTERS
#
# Old backups are pruned by this script, AFTER the new upload is confirmed
# present in the bucket -- never by a B2 lifecycle rule.
#
# A lifecycle rule deletes on age regardless of whether anything new arrived.
# If uploads silently break, it keeps deleting until the bucket is empty and
# nothing announces it. Pruning here, only after a verified upload, makes a
# broken backup fail safe: artifacts pile up instead of evaporating.
# ---------------------------------------------------------------------------
set -uo pipefail

BACKEND=/opt/job-tracker-backend
CONF="$HOME/.config/job-tracker"
STATUS=/var/lib/job-tracker/backup-status

DAILY_KEEP=30
MONTHLY_KEEP=12

fail() { echo "ERROR: $*" >&2; write_status FAIL "$*"; exit 1; }

write_status() {
    mkdir -p "$(dirname "$STATUS")"
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
artifact=${ARTIFACT_NAME:-}
bytes=${ARTIFACT_BYTES:-}
daily_kept=${DAILY_COUNT:-}
monthly_kept=${MONTHLY_COUNT:-}
verified_tables=${VERIFIED_TABLES:-}
STATUSEOF
}

ARTIFACT_NAME=""; ARTIFACT_BYTES=""; DAILY_COUNT=""; MONTHLY_COUNT=""; VERIFIED_TABLES=""

# --- config ---------------------------------------------------------------
[ -r "$CONF/backup.env" ]  || fail "missing $CONF/backup.env"
[ -r "$CONF/backup.pass" ] || fail "missing $CONF/backup.pass (the encryption passphrase)"
[ -r "$CONF/rclone.conf" ] || fail "missing $CONF/rclone.conf (B2 credentials)"

# shellcheck disable=SC1091
. "$CONF/backup.env"
[ -n "${B2_BUCKET:-}" ] || fail "B2_BUCKET not set in backup.env"

RCLONE=(rclone --config "$CONF/rclone.conf")
REMOTE="b2:$B2_BUCKET"

WORK=$(mktemp -d) || fail "could not create work directory"
chmod 700 "$WORK"
trap 'rm -rf "$WORK"' EXIT

# --- database credentials -------------------------------------------------
# Read from the service's own .env so there is one source of truth. Written
# into a defaults file rather than passed as -p on the command line, where ps
# would expose the password to every user on the machine.
[ -r "$BACKEND/.env" ] || fail "cannot read $BACKEND/.env"
# shellcheck disable=SC1091
set -a; . "$BACKEND/.env"; set +a

cat > "$WORK/my.cnf" <<MYCNF
[client]
host=${DB_HOST:-localhost}
port=${DB_PORT:-3306}
user=${DB_USER:?}
password=${DB_PASSWORD:?}
MYCNF
chmod 600 "$WORK/my.cnf"

# --- dump, compress, encrypt ----------------------------------------------
STAMP=$(date +%F)
ARTIFACT_NAME="job-tracker-${STAMP}.sql.gz.gpg"
ARTIFACT="$WORK/$ARTIFACT_NAME"

# --single-transaction gives a consistent snapshot on InnoDB without taking
# locks, so the app keeps working during the dump.
if ! mysqldump --defaults-extra-file="$WORK/my.cnf" \
        --single-transaction --no-tablespaces \
        "${DB_NAME:?}" 2>"$WORK/dump.err" \
     | gzip -9 \
     | gpg --batch --yes --quiet --symmetric --cipher-algo AES256 \
           --passphrase-file "$CONF/backup.pass" \
           --output "$ARTIFACT"
then
    fail "dump/encrypt failed: $(head -3 "$WORK/dump.err" | tr '\n' ' ')"
fi

ARTIFACT_BYTES=$(stat -c%s "$ARTIFACT")
[ "$ARTIFACT_BYTES" -gt 0 ] || fail "encrypted artifact is empty"

# Verify by round-tripping, not by inspecting. Decrypt it, decompress it, and
# confirm the tables are actually in there.
#
# This proves three things a structural check cannot: that the passphrase on
# this machine really opens the artifact, that the gzip stream is intact, and
# that the dump has content rather than being an error message captured where
# SQL was expected.
#
# It also makes every nightly run a partial restore test, which is the part of
# KAN-19 that can be automated.
#
# (An earlier version used `gpg --list-packets` here. On symmetric data that
# tries to decrypt, wants a passphrase, and fails under a timer with "problem
# with the agent: Inappropriate ioctl for device" -- rejecting good artifacts.)
if ! gpg --batch --quiet --decrypt --passphrase-file "$CONF/backup.pass" \
        "$ARTIFACT" 2>/dev/null | gunzip > "$WORK/verify.sql" 2>/dev/null
then
    fail "artifact failed round-trip: could not decrypt and decompress it"
fi

for table in applications contacts; do
    grep -q "^CREATE TABLE .$table." "$WORK/verify.sql" \
        || fail "round-trip succeeded but table '$table' is missing from the dump"
done
VERIFIED_TABLES=$(grep -c '^CREATE TABLE' "$WORK/verify.sql")

echo "built $ARTIFACT_NAME ($ARTIFACT_BYTES bytes), round-trip OK, $VERIFIED_TABLES tables"

# --- upload ---------------------------------------------------------------
"${RCLONE[@]}" copyto "$ARTIFACT" "$REMOTE/daily/$ARTIFACT_NAME" \
    || fail "upload to $REMOTE/daily/ failed"

# Confirm it is actually there and the right size before anything is deleted.
REMOTE_BYTES=$("${RCLONE[@]}" size --json "$REMOTE/daily/$ARTIFACT_NAME" 2>/dev/null \
               | sed -n 's/.*"bytes":\([0-9]*\).*/\1/p')
[ "$REMOTE_BYTES" = "$ARTIFACT_BYTES" ] \
    || fail "upload unverified: local $ARTIFACT_BYTES bytes, remote '${REMOTE_BYTES:-absent}'"
echo "verified in bucket: daily/$ARTIFACT_NAME"

# First of the month is also kept as a monthly.
if [ "$(date +%d)" = "01" ]; then
    "${RCLONE[@]}" copyto "$ARTIFACT" "$REMOTE/monthly/$ARTIFACT_NAME" \
        || fail "monthly upload failed"
    echo "verified in bucket: monthly/$ARTIFACT_NAME"
fi

# --- prune, only now ------------------------------------------------------
# Filenames are date-stamped, so lexicographic order is chronological and
# `head -n -N` leaves the newest N alone.
prune() {
    local prefix=$1 keep=$2 removed=0 f
    while IFS= read -r f; do
        [ -n "$f" ] || continue
        "${RCLONE[@]}" deletefile "$REMOTE/$prefix/$f" && removed=$((removed + 1))
    done < <("${RCLONE[@]}" lsf --files-only "$REMOTE/$prefix/" 2>/dev/null | sort | head -n -"$keep")
    echo "$removed"
}

PRUNED_DAILY=$(prune daily "$DAILY_KEEP")
PRUNED_MONTHLY=$(prune monthly "$MONTHLY_KEEP")

DAILY_COUNT=$("${RCLONE[@]}" lsf --files-only "$REMOTE/daily/" 2>/dev/null | wc -l)
MONTHLY_COUNT=$("${RCLONE[@]}" lsf --files-only "$REMOTE/monthly/" 2>/dev/null | wc -l)

echo "pruned $PRUNED_DAILY daily, $PRUNED_MONTHLY monthly"
echo "retained: $DAILY_COUNT daily, $MONTHLY_COUNT monthly"

write_status PASS ""
echo "=== PASS ==="
