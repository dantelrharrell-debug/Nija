#!/bin/sh
# start_all.sh - start non-web background workers, then run web server in foreground.
set -eu

LOGDIR="/app/logs"
PORT="${PORT:-5000}"

mkdir -p "$LOGDIR"

start_bg() {
  script="$1"
  logfile="$LOGDIR/$(basename "$script").log"
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
# NOTE: main.py is intentionally NOT started here because it contains the webserver.
start_bg tv_webhook_listener.py
start_bg coinbase_trader.py

echo "$(date -u +'%Y-%m-%dT%H:%M:%SZ') start_all.sh: launching web process in foreground"

# Prefer wsgi wrapper (wsgi:app), then candidates. This will exec the web server and keep container alive.
if command -v gunicorn >/dev/null 2>&1 ; then
  if python -c "import importlib; importlib.import_module('wsgi')" >/dev/null 2>&1; then
    echo "Starting gunicorn wsgi:app on 0.0.0.0:$PORT"
    exec gunicorn --bind 0.0.0.0:"$PORT" wsgi:app
  fi

  CANDIDATES="web.wsgi:app web.app:app web:app main:app app:app"
  for cand in $CANDIDATES; do
    module=$(echo "$cand" | cut -d: -f1)
    if python -c "import importlib; importlib.import_module('$module')" >/dev/null 2>&1; then
      echo "Starting gunicorn $cand on 0.0.0.0:$PORT"
      exec gunicorn --bind 0.0.0.0:"$PORT" "$cand"
    fi
  done
fi

if command -v uvicorn >/dev/null 2>&1 ; then
  if python -c "import importlib; importlib.import_module('wsgi')" >/dev/null 2>&1; then
    echo "Starting uvicorn wsgi:app on 0.0.0.0:$PORT"
    exec uvicorn wsgi:app --host 0.0.0.0 --port "$PORT"
  fi
fi

echo "No app entrypoint found; falling back to python -m http.server on $PORT"
exec python -m http.server "$PORT"
