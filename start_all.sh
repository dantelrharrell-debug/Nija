#!/bin/sh
# start_all.sh - conservative startup script for the app
# - starts long-running "bot" processes in background and runs the webserver in foreground
# - logs per-process to /app/logs/*
# - safe: checks files exist before launching

set -eu

LOGDIR="/app/logs"
PORT="${PORT:-8000}"

mkdir -p "$LOGDIR"

start_bg() {
  script="$1"
  logfile="$LOGDIR/$(basename "$script").log"
  if [ -f "$script" ]; then
    echo "$(date -u +'%Y-%m-%dT%H:%M:%SZ') starting $script -> $logfile"
    # nohup so backgrounded processes survive; redirect stdout/stderr
    nohup python "$script" >> "$logfile" 2>&1 &
  else
    echo "$(date -u +'%Y-%m-%dT%H:%M:%SZ') skipping $script (not found)"
  fi
}

echo "== start_all.sh: starting background workers (if present) =="
# Start expected background processes if they exist
start_bg main.py
start_bg tv_webhook_listener.py
start_bg coinbase_trader.py

echo "== start_all.sh: launching web process in foreground =="
# Start web server in foreground (gunicorn preferred). Try multiple common entrypoints.
if command -v gunicorn >/dev/null 2>&1; then
  if [ -f "web/app.py" ]; then
    echo "Starting gunicorn web.app:app on 0.0.0.0:$PORT"
    exec gunicorn --bind 0.0.0.0:"$PORT" web.app:app
  elif [ -f "web/__init__.py" ]; then
    echo "Starting gunicorn web:app on 0.0.0.0:$PORT"
    exec gunicorn --bind 0.0.0.0:"$PORT" web:app
  elif [ -f "web.py" ]; then
    echo "Starting gunicorn web:app (fallback) on 0.0.0.0:$PORT"
    exec gunicorn --bind 0.0.0.0:"$PORT" web:app
  else
    echo "Gunicorn available but no common web entrypoint found; falling back to python -m http.server"
    exec python -m http.server "$PORT"
  fi
else
  echo "gunicorn not found; falling back to built-in server on $PORT"
  exec python -m http.server "$PORT"
fi
