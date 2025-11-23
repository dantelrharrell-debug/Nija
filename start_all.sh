#!/bin/sh
# start_all.sh - conservative startup script with robust WSGI/ASGI detection.
# Starts expected background scripts (if present) and launches a web server in foreground.
# Writes logs to /app/logs/.
set -eu

LOGDIR="/app/logs"
PORT="${PORT:-8000}"

mkdir -p "$LOGDIR"

start_bg() {
  script="$1"
  logfile="$LOGDIR/$(basename "$script").log"
  # Avoid launching duplicates if a process is already running
  if pgrep -f "$(basename "$script")" >/dev/null 2>&1; then
    echo "$(date -u +'%Y-%m-%dT%H:%M:%SZ') skipping $script (already running)"
    return
  fi
  if [ -f "$script" ]; then
    echo "$(date -u +'%Y-%m-%dT%H:%M:%SZ') launching: python $script -> $logfile"
    nohup python "$script" >> "$logfile" 2>&1 &
  else
    echo "$(date -u +'%Y-%m-%dT%H:%M:%SZ') skipping $script (not found)"
  fi
}

echo "$(date -u +'%Y-%m-%dT%H:%M:%SZ') start_all.sh: starting background workers (if present)"
start_bg main.py
start_bg tv_webhook_listener.py
start_bg coinbase_trader.py

echo "$(date -u +'%Y-%m-%dT%H:%M:%SZ') start_all.sh: launching web process in foreground"

# Candidate entrypoints to try (module:app)
CANDIDATES="web.app:app web:app main:app app:app"

# Prefer gunicorn (WSGI) if present
if command -v gunicorn >/dev/null 2>&1 ; then
  for cand in $CANDIDATES; do
    module=$(echo "$cand" | cut -d: -f1)
    if python -c "import importlib; importlib.import_module('$module')" >/dev/null 2>&1; then
      echo "Starting gunicorn $cand on 0.0.0.0:$PORT"
      exec gunicorn --bind 0.0.0.0:"$PORT" "$cand"
    fi
  done
fi

# Try uvicorn for ASGI apps (FastAPI/Starlette)
if command -v uvicorn >/dev/null 2>&1 ; then
  for cand in $CANDIDATES; do
    module=$(echo "$cand" | cut -d: -f1)
    if python -c "import importlib; importlib.import_module('$module')" >/dev/null 2>&1; then
      echo "Starting uvicorn $cand on 0.0.0.0:$PORT"
      exec uvicorn "$cand" --host 0.0.0.0 --port "$PORT"
    fi
  done
fi

# Flask fallback if flask CLI exists and web package looks like a Flask app
if [ -f "web/app.py" ] || [ -f "web/__init__.py" ]; then
  if command -v flask >/dev/null 2>&1 ; then
    echo "Starting flask run on 0.0.0.0:$PORT"
    FLASK_APP=web.app exec flask run --host=0.0.0.0 --port="$PORT"
  fi
fi

# Last resort: static server to keep container up (no dynamic endpoints)
echo "No WSGI/ASGI entrypoint found or servers missing; falling back to python -m http.server on port $PORT"
exec python -m http.server "$PORT"
