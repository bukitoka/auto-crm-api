#!/bin/sh
set -e

# A failed migration must stop the deploy, not start the API on an outdated schema.
echo "Running database migrations..."
alembic upgrade head

echo "Starting Auto CRM API..."
# Behind Caddy on the Docker network, so the forwarded client IP is trustworthy.
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips='*'
