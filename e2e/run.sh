#!/usr/bin/env bash
# End-to-end tests with Newman:
#   fresh `auto_crm_e2e` database -> migrations -> API on :8001 -> Postman collection.
# The dev database (auto_crm) and bucket (auto-crm) are never touched; no email is sent.
# Exit code = Newman's exit code.
set -euo pipefail

cd "$(dirname "$0")/.." # the API repo root

E2E_DB="auto_crm_e2e"
E2E_PORT=8001
E2E_API_KEY="e2e-api-key" # must match apiKey in e2e.postman_environment.json
NEWMAN_VERSION="6.2.1"
PG_CONTAINER="auto-crm-postgres"
RESULTS_DIR="e2e/results"

# Same host port as docker compose (POSTGRES_PORT in .env, default 5432).
POSTGRES_PORT=$(grep -E '^POSTGRES_PORT=' .env 2>/dev/null | cut -d= -f2 || true)
POSTGRES_PORT=${POSTGRES_PORT:-5432}
E2E_DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:${POSTGRES_PORT}/${E2E_DB}"

mkdir -p "$RESULTS_DIR"

echo "==> Starting Postgres and MinIO (docker compose)"
docker compose up -d --wait postgres minio

echo "==> Recreating database ${E2E_DB}"
docker exec "$PG_CONTAINER" psql -U postgres -q -c "DROP DATABASE IF EXISTS ${E2E_DB} WITH (FORCE)"
docker exec "$PG_CONTAINER" psql -U postgres -q -c "CREATE DATABASE ${E2E_DB}"

echo "==> Running migrations"
DATABASE_URL="$E2E_DATABASE_URL" uv run alembic upgrade head

if curl -sf "http://localhost:${E2E_PORT}/health" >/dev/null; then
  echo "Port ${E2E_PORT} is already in use. Stop that server and try again." >&2
  exit 1
fi

echo "==> Starting the API on port ${E2E_PORT} (log: ${RESULTS_DIR}/api.log)"
# Environment variables override the values in .env.
DATABASE_URL="$E2E_DATABASE_URL" \
  AUTOMATION_API_KEY="$E2E_API_KEY" \
  DEEPSEEK_API_KEY="" \
  S3_BUCKET="auto-crm-e2e" \
  uv run uvicorn app.main:app --port "$E2E_PORT" >"${RESULTS_DIR}/api.log" 2>&1 &
API_PID=$!

stop_api() {
  echo "==> Stopping the API"
  kill "$API_PID" 2>/dev/null || true
  wait "$API_PID" 2>/dev/null || true
}
trap stop_api EXIT

echo "==> Waiting for /health"
for _ in $(seq 1 30); do
  if curl -sf "http://localhost:${E2E_PORT}/health" >/dev/null; then
    break
  fi
  sleep 1
done
curl -sf "http://localhost:${E2E_PORT}/health" >/dev/null || {
  echo "The API did not start. See ${RESULTS_DIR}/api.log" >&2
  exit 1
}

echo "==> Running Newman ${NEWMAN_VERSION}"
set +e
bunx "newman@${NEWMAN_VERSION}" run e2e/auto-crm.postman_collection.json \
  --environment e2e/e2e.postman_environment.json \
  --reporters cli,junit \
  --reporter-junit-export "${RESULTS_DIR}/junit.xml"
NEWMAN_STATUS=$?
set -e

exit "$NEWMAN_STATUS"
