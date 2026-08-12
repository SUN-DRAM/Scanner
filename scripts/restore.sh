#!/usr/bin/env bash
# Gate C: restore a backup produced by scripts/backup.sh.
#
# Default target is a throwaway scratch Postgres container — this is what
# "documented restore that you have actually tested by restoring into a
# scratch container" (docs/PHASE_1_GATE.md, Gate C item 4) means: prove the
# backup is actually restorable *before* you ever need it for real, without
# touching the live database to find out.
#
# Usage:
#   ./scripts/restore.sh                        # latest backup -> scratch container
#   ./scripts/restore.sh scanner-20260811-020000.sql.gz
#   ./scripts/restore.sh latest --target=prod    # disaster recovery: overwrites the LIVE database
#
# --target=prod requires typing a confirmation phrase — see docs/DEPLOY.md's
# "Restore from backup" step for the full runbook, including stopping
# api/worker first so nothing writes to the database mid-restore.

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

COMPOSE_FILE="docker-compose.prod.yml"
ENV_FILE=".env"
SCRATCH_CONTAINER="scanner-restore-scratch"
SCRATCH_PORT="55432"

if [[ ! -f "$ENV_FILE" ]]; then
    echo "restore.sh: $ENV_FILE not found — run from the repo root on the deploy host." >&2
    exit 1
fi

# shellcheck disable=SC1090
set -a
source "$ENV_FILE"
set +a

: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD must be set in .env}"
: "${DO_SPACES_BUCKET:?DO_SPACES_BUCKET must be set in .env}"
: "${DO_SPACES_ENDPOINT:?DO_SPACES_ENDPOINT must be set in .env}"
: "${DO_SPACES_REGION:?DO_SPACES_REGION must be set in .env}"
: "${DO_SPACES_ACCESS_KEY_ID:?DO_SPACES_ACCESS_KEY_ID must be set in .env}"
: "${DO_SPACES_SECRET_ACCESS_KEY:?DO_SPACES_SECRET_ACCESS_KEY must be set in .env}"

export AWS_ACCESS_KEY_ID="$DO_SPACES_ACCESS_KEY_ID"
export AWS_SECRET_ACCESS_KEY="$DO_SPACES_SECRET_ACCESS_KEY"
export AWS_DEFAULT_REGION="$DO_SPACES_REGION"

BACKUP_ARG="${1:-latest}"
TARGET="scratch"
for arg in "$@"; do
    case "$arg" in
        --target=*) TARGET="${arg#--target=}" ;;
    esac
done

if [[ "$TARGET" != "scratch" && "$TARGET" != "prod" ]]; then
    echo "restore.sh: --target must be 'scratch' or 'prod', got '${TARGET}'." >&2
    exit 1
fi

# --- resolve which backup to restore ---

if [[ "$BACKUP_ARG" == "latest" || "$BACKUP_ARG" == --target=* ]]; then
    echo "restore.sh: resolving latest backup in s3://${DO_SPACES_BUCKET}/backups/..."
    DUMP_NAME="$(aws s3 ls "s3://${DO_SPACES_BUCKET}/backups/" --endpoint-url "$DO_SPACES_ENDPOINT" \
        | awk '{print $4}' | grep '^scanner-' | sort | tail -n1)"
    if [[ -z "$DUMP_NAME" ]]; then
        echo "restore.sh: no backups found in the bucket." >&2
        exit 1
    fi
else
    DUMP_NAME="$BACKUP_ARG"
fi

echo "restore.sh: restoring ${DUMP_NAME} -> target=${TARGET}"

LOCAL_DIR="$(mktemp -d)"
LOCAL_DUMP="${LOCAL_DIR}/${DUMP_NAME}"
cleanup() {
    rm -rf "$LOCAL_DIR"
}
trap cleanup EXIT

aws s3 cp "s3://${DO_SPACES_BUCKET}/backups/${DUMP_NAME}" "$LOCAL_DUMP" \
    --endpoint-url "$DO_SPACES_ENDPOINT" \
    --only-show-errors

# --- scratch: a disposable container, never the live database ---

if [[ "$TARGET" == "scratch" ]]; then
    echo "restore.sh: starting a scratch postgres container on port ${SCRATCH_PORT}..."
    docker rm -f "$SCRATCH_CONTAINER" >/dev/null 2>&1 || true
    docker run -d --name "$SCRATCH_CONTAINER" \
        -e POSTGRES_USER=scanner -e POSTGRES_PASSWORD=scratch -e POSTGRES_DB=scanner \
        -p "${SCRATCH_PORT}:5432" \
        postgres:16-alpine >/dev/null

    echo "restore.sh: waiting for scratch container to accept connections..."
    for _ in $(seq 1 30); do
        if docker exec "$SCRATCH_CONTAINER" pg_isready -U scanner -d scanner >/dev/null 2>&1; then
            break
        fi
        sleep 1
    done

    echo "restore.sh: loading dump into scratch container..."
    gunzip -c "$LOCAL_DUMP" | docker exec -i "$SCRATCH_CONTAINER" psql -U scanner -d scanner -q

    echo "restore.sh: verifying — row counts in the restored scratch database:"
    docker exec "$SCRATCH_CONTAINER" psql -U scanner -d scanner -c \
        "SELECT 'scans' AS table_name, count(*) FROM scans
         UNION ALL SELECT 'waitlist_signups', count(*) FROM waitlist_signups
         UNION ALL SELECT 'daily_stats', count(*) FROM daily_stats;"

    echo
    echo "restore.sh: scratch restore verified. The scratch container is still running:"
    echo "  psql -h localhost -p ${SCRATCH_PORT} -U scanner -d scanner   (password: scratch)"
    echo "When done inspecting it, remove it with:"
    echo "  docker rm -f ${SCRATCH_CONTAINER}"
    exit 0
fi

# --- prod: overwrites the live database, requires explicit confirmation ---

echo
echo "!!! restore.sh: --target=prod will REPLACE every row in the live production database"
echo "!!! with the contents of ${DUMP_NAME}. This cannot be undone."
echo
read -r -p "Type 'yes-overwrite-production' to continue: " CONFIRMATION
if [[ "$CONFIRMATION" != "yes-overwrite-production" ]]; then
    echo "restore.sh: confirmation not given, aborting. Nothing was changed."
    exit 1
fi

echo "restore.sh: stopping api and worker so nothing writes during the restore..."
docker compose -f "$COMPOSE_FILE" stop api worker

echo "restore.sh: loading dump into the production database..."
gunzip -c "$LOCAL_DUMP" | docker compose -f "$COMPOSE_FILE" exec -T postgres \
    psql -U scanner -d scanner -q

echo "restore.sh: restore complete. Restarting api and worker..."
docker compose -f "$COMPOSE_FILE" start api worker

echo "restore.sh: done. Confirm with: curl -s https://sundram.tech/api/v1/health"
