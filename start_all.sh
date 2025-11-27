#!/usr/bin/env bash
set -euo pipefail

# start_all.sh
# - Runs nija_client.py in a monitored background loop
# - Starts Gunicorn with the web app
# Environment:
#   PORT (optional, default 8080)
#   LOG_LEVEL - forwarded to Python logging
#   LIVE_TRADING - if '1' the client tries live mode

PORT="${PORT:-8080}"
GUNICORN_WORKERS="${GUNICORN_WORKERS:-2}"
GUNICORN_THREADS="${GUNICORN_THREADS:-2}"
GUNICORN_MODULE="${GUNICORN_MODULE:-web.wsgi:app}"

echo "$(date -u +'%Y-%m-%dT%H:%M:%SZ') | .env not present — using environment variables provided by the host."

# start background trading loop
(
  while true; do
    echo "$(date -u +'%Y-%m-%dT%H:%M:%SZ') | Starting Nija trading bot (background loop)..."
    # run nija_client in foreground so crashes show logs; script will restart it after exit
    python3 /app/nija_client.py || echo "$(date -u +'%Y-%m-%dT%H:%M:%SZ') | nija_client exited/crashed; restarting in 2s..."
    sleep 2
  done
) &

# Give the background a moment to initialize
sleep 1

# start gunicorn for the web app (bind to $PORT)
echo "$(date -u +'%Y-%m-%dT%H:%M:%SZ') | Starting Gunicorn web server..."
exec gunicorn -w "${GUNICORN_WORKERS}" --threads "${GUNICORN_THREADS}" -b 0.0.0.0:"${PORT}" "${GUNICORN_MODULE}"
