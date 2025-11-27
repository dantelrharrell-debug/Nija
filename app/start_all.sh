#!/usr/bin/env bash
set -euo pipefail

PORT="${PORT:-8080}"
GUNICORN_WORKERS="${GUNICORN_WORKERS:-2}"
GUNICORN_THREADS="${GUNICORN_THREADS:-2}"
GUNICORN_MODULE="${GUNICORN_MODULE:-web.wsgi:app}"

echo "$(date -u +'%Y-%m-%dT%H:%M:%SZ') | .env not present — using environment variables provided by the host."
(
  while true; do
    echo "$(date -u +'%Y-%m-%dT%H:%M:%SZ') | Starting Nija trading bot (background loop)..."
    # run nija_client in foreground so crashes show logs
    python3 /app/nija_client.py || echo "$(date -u +'%Y-%m-%dT%H:%M:%SZ') | nija_client exited/crashed; restarting in 2s..."
    sleep 2
  done
) &

sleep 1

echo "$(date -u +'%Y-%m-%dT%H:%M:%SZ') | Starting Gunicorn web server..."
exec gunicorn -w "${GUNICORN_WORKERS}" --threads "${GUNICORN_THREADS}" -b 0.0.0.0:"${PORT}" "${GUNICORN_MODULE}"
