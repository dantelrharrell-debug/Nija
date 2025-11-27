#!/usr/bin/env bash
set -euo pipefail

PORT="${PORT:-8080}"
GUNICORN_WORKERS="${GUNICORN_WORKERS:-2}"
GUNICORN_THREADS="${GUNICORN_THREADS:-2}"
GUNICORN_MODULE="${GUNICORN_MODULE:-web.wsgi:app}"

echo "$(date -u +'%Y-%m-%dT%H:%M:%SZ') | .env not present — using environment variables provided by the host."

# Start trading runner in background
(
  while true; do
    echo "$(date -u +'%Y-%m-%dT%H:%M:%SZ') | Starting Nija trading bot (background loop)..."
    # run the dedicated runner (keeps import-time of nija_client safe)
    python3 -u /app/nija_bot_runner.py || echo "$(date -u +'%Y-%m-%dT%H:%M:%SZ') | nija_bot_runner exited; restarting in 2s..."
    sleep 2
  done
) &

sleep 1

echo "$(date -u +'%Y-%m-%dT%H:%M:%SZ') | Starting Gunicorn web server..."
exec gunicorn -w "${GUNICORN_WORKERS}" --threads "${GUNICORN_THREADS}" -b 0.0.0.0:"${PORT}" "${GUNICORN_MODULE}"
