#!/usr/bin/env bash
set -euo pipefail

# Start all services: bot loop (background) + Gunicorn for Flask
# This script is executed as the container's CMD.

LOG() { echo "$(date -u +'%Y-%m-%dT%H:%M:%SZ') | $*"; }

# load .env if present (non-fatal)
if [ -f "/app/.env" ]; then
  # shellcheck disable=SC1091
  set -a
  # Use grep -v to ignore blank lines and comments
  grep -v '^\s*#' /app/.env | sed '/^\s*$/d' > /tmp/.env.parsed || true
  # shellcheck disable=SC1091
  . /tmp/.env.parsed || true
  set +a
  LOG "Loaded /app/.env"
else
  LOG ".env not present — using environment variables provided by the host."
fi

# ensure python path includes vendor dir
export PYTHONPATH="/app/vendor:${PYTHONPATH:-}"

# start bot in a restart loop in background
LOG "Starting Nija trading bot (background loop)..."
(
  while true; do
    LOG "Launching nija_client.py"
    python3 /app/nija_client.py || LOG "nija_client crashed ($?). Restarting in 2s..."
    sleep 2
  done
) &

# wait a moment to let bot initialize
sleep 1

# Start Gunicorn (web app). Expose web.wsgi:app
LOG "Starting Gunicorn web server..."
# If you have a gunicorn.conf.py use it; otherwise default options used.
if [ -f "/app/gunicorn.conf.py" ]; then
  exec gunicorn -c /app/gunicorn.conf.py web.wsgi:app
else
  exec gunicorn -w 2 -k gthread --threads 2 -b 0.0.0.0:${PORT:-8080} web.wsgi:app
fi
