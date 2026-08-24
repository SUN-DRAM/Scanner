#!/usr/bin/env bash
# Redeploy the production stack: pull, rebuild, migrate, health-check, and
# roll back automatically if the health check fails. Run from the repo root
# on the production host (ubuntu@65.2.195.179), e.g.:
#   cd /opt/scanner && ./scripts/deploy.sh
#
# "Rollback" here means: check out the commit that was running before this
# script started and rebuild from it. It does NOT run `alembic downgrade`.
# Per docs/DEPLOY.md's rollback section, reverting a schema migration is a
# deliberate, separate, human judgment call — a bad downgrade can lose data
# in ways a bad code deploy can't — so this script never does it unattended.
# If a rollback fires and this deploy included a migration, follow
# docs/DEPLOY.md section 5 to decide whether `alembic downgrade -1` is safe.

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

COMPOSE_FILE="docker-compose.prod.yml"
ENV_FILE=".env"
HEALTH_URL="http://localhost:8000/api/v1/health"
HEALTH_RETRIES=10
HEALTH_RETRY_DELAY_SECONDS=3

if [[ ! -f "$ENV_FILE" ]]; then
    echo "deploy.sh: $ENV_FILE not found — run from the repo root on the deploy host." >&2
    exit 1
fi

if [[ -n "$(git status --porcelain)" ]]; then
    echo "deploy.sh: working tree has uncommitted changes — refusing to deploy over them." >&2
    echo "deploy.sh: commit, stash, or discard them first." >&2
    exit 1
fi

PREVIOUS_SHA="$(git rev-parse HEAD)"
echo "deploy.sh: current commit ${PREVIOUS_SHA}"

echo "deploy.sh: pulling latest..."
git pull --ff-only

NEW_SHA="$(git rev-parse HEAD)"
if [[ "$NEW_SHA" == "$PREVIOUS_SHA" ]]; then
    echo "deploy.sh: already up to date, nothing to deploy."
    exit 0
fi
echo "deploy.sh: deploying ${PREVIOUS_SHA} -> ${NEW_SHA}"

rollback() {
    echo "deploy.sh: !!! failed, rolling back to ${PREVIOUS_SHA} !!!" >&2
    git checkout "$PREVIOUS_SHA"
    docker compose -f "$COMPOSE_FILE" up -d --build
    echo "deploy.sh: rolled back to ${PREVIOUS_SHA}. If this deploy included a migration," >&2
    echo "deploy.sh: decide separately whether 'alembic downgrade -1' is needed — see docs/DEPLOY.md section 5." >&2
    exit 1
}

echo "deploy.sh: building and restarting changed services..."
docker compose -f "$COMPOSE_FILE" up -d --build

echo "deploy.sh: running migrations..."
if ! docker compose -f "$COMPOSE_FILE" exec -T api alembic upgrade head; then
    rollback
fi

echo "deploy.sh: waiting for health check at ${HEALTH_URL}..."
for attempt in $(seq 1 "$HEALTH_RETRIES"); do
    body="$(docker compose -f "$COMPOSE_FILE" exec -T api curl -s "$HEALTH_URL" || true)"
    if [[ "$body" == *'"status":"ok"'* || "$body" == *'"status": "ok"'* ]]; then
        echo "deploy.sh: health check passed on attempt ${attempt} (status: ok)."
        echo "deploy.sh: deploy complete. Now live at ${NEW_SHA}."
        exit 0
    fi
    echo "deploy.sh: health check attempt ${attempt}/${HEALTH_RETRIES} not ok yet (got: ${body:-no response}), retrying in ${HEALTH_RETRY_DELAY_SECONDS}s..."
    sleep "$HEALTH_RETRY_DELAY_SECONDS"
done

echo "deploy.sh: health check did not report 'ok' within $((HEALTH_RETRIES * HEALTH_RETRY_DELAY_SECONDS))s." >&2
rollback
