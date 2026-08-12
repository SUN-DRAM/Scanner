#!/usr/bin/env bash
# Gate C: nightly Postgres backup to DigitalOcean Spaces (S3-compatible).
# Run from the repo root on the production host, e.g. via cron:
#   0 2 * * * cd /opt/sun-dram-scanner && ./scripts/backup.sh >> /var/log/scanner-backup.log 2>&1
#
# Requires: docker compose (the prod stack already running), aws-cli v2
# (works against DO Spaces via --endpoint-url — no separate tool needed),
# and every DO_SPACES_* / POSTGRES_PASSWORD variable in .env.production.example
# actually set in .env.
#
# Never prints POSTGRES_PASSWORD or the Spaces secret key — both are only
# ever read into environment variables the AWS CLI and pg_dump consume
# directly, never echoed or logged.

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

COMPOSE_FILE="docker-compose.prod.yml"
ENV_FILE=".env"

if [[ ! -f "$ENV_FILE" ]]; then
    echo "backup.sh: $ENV_FILE not found — run from the repo root on the deploy host." >&2
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

BACKUP_RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-30}"
TIMESTAMP="$(date -u +%Y%m%d-%H%M%S)"
DUMP_NAME="scanner-${TIMESTAMP}.sql.gz"
LOCAL_DIR="$(mktemp -d)"
LOCAL_DUMP="${LOCAL_DIR}/${DUMP_NAME}"

# aws-cli reads these standard names; DO Spaces keys are handed to it under
# those names rather than inventing a parallel set of AWS_* variables to keep
# in sync by hand.
export AWS_ACCESS_KEY_ID="$DO_SPACES_ACCESS_KEY_ID"
export AWS_SECRET_ACCESS_KEY="$DO_SPACES_SECRET_ACCESS_KEY"
export AWS_DEFAULT_REGION="$DO_SPACES_REGION"

cleanup() {
    rm -rf "$LOCAL_DIR"
}
trap cleanup EXIT

echo "backup.sh: dumping database via docker compose exec postgres pg_dump..."
# --clean --if-exists: the dump includes DROP statements before each CREATE,
# so restore.sh can pipe it straight into `psql` against an empty *or*
# already-populated database (scratch verification, or a real disaster
# recovery restore) without a separate schema-wipe step first.
docker compose -f "$COMPOSE_FILE" exec -T postgres \
    pg_dump -U scanner -d scanner --no-owner --no-privileges --clean --if-exists \
    | gzip -9 > "$LOCAL_DUMP"

DUMP_SIZE="$(du -h "$LOCAL_DUMP" | cut -f1)"
echo "backup.sh: dump complete (${DUMP_SIZE}), uploading to s3://${DO_SPACES_BUCKET}/backups/${DUMP_NAME}"

aws s3 cp "$LOCAL_DUMP" "s3://${DO_SPACES_BUCKET}/backups/${DUMP_NAME}" \
    --endpoint-url "$DO_SPACES_ENDPOINT" \
    --only-show-errors

echo "backup.sh: upload complete."

# Prune backups older than BACKUP_RETENTION_DAYS in the bucket. Listing and
# deleting individually rather than a lifecycle rule: lifecycle policies are
# a one-time Spaces console/API setup this script can't assume is present,
# and this way the retention window is visible and changeable in one place
# (.env) rather than split between here and a bucket-side policy.
echo "backup.sh: pruning backups older than ${BACKUP_RETENTION_DAYS} days..."
CUTOFF_EPOCH="$(date -u -d "-${BACKUP_RETENTION_DAYS} days" +%s 2>/dev/null || date -u -v-"${BACKUP_RETENTION_DAYS}"d +%s)"

aws s3 ls "s3://${DO_SPACES_BUCKET}/backups/" --endpoint-url "$DO_SPACES_ENDPOINT" \
    | while read -r line; do
        FILE_DATE="$(echo "$line" | awk '{print $1" "$2}')"
        FILE_NAME="$(echo "$line" | awk '{print $4}')"
        [[ -z "$FILE_NAME" ]] && continue
        FILE_EPOCH="$(date -u -d "$FILE_DATE" +%s 2>/dev/null || true)"
        [[ -z "$FILE_EPOCH" ]] && continue
        if (( FILE_EPOCH < CUTOFF_EPOCH )); then
            echo "backup.sh: deleting expired backup ${FILE_NAME}"
            aws s3 rm "s3://${DO_SPACES_BUCKET}/backups/${FILE_NAME}" --endpoint-url "$DO_SPACES_ENDPOINT"
        fi
    done

echo "backup.sh: done. Latest backup: ${DUMP_NAME}"
