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
: "${S3_BACKUP_BUCKET:?S3_BACKUP_BUCKET must be set in .env}"

# Credentials come from the EC2 instance's IAM role, not from .env — see the
# comment in backup.sh.
AWS_REGION="${AWS_REGION:-ap-south-1}"

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
    echo "restore.sh: resolving latest backup in s3://${S3_BACKUP_BUCKET}/backups/..."
    DUMP_NAME="$(aws s3 ls "s3://${S3_BACKUP_BUCKET}/backups/" --region "$AWS_REGION" \
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

aws s3 cp "s3://${S3_BACKUP_BUCKET}/backups/${DUMP_NAME}" "$LOCAL_DUMP" \
    --region "$AWS_REGION" \
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
