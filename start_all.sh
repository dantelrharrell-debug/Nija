#!/usr/bin/env bash
set -euo pipefail

# Default PORT
PORT=${PORT:-5000}

LOGDIR=/app/logs
mkdir -p "$LOGDIR"

timestamp() {
  date -u +"%Y-%m-%dT%H:%M:%SZ"
}

echo "$(timestamp) [inf] start_all.sh: starting background workers (if present)"

# Helper to launch a background worker with logging
start_bg() {
  local cmd="$1"
  local logfile="$2"
  echo "$(timestamp) [inf] launching: $cmd -> $logfile"
  # Run in background with nohup to survive when called non-interactively
  nohup bash -lc "$cmd" > "$logfile" 2>&1 &
  sleep 0.2
}

# -- Start background workers (adjust these commands if your filenames differ) --
# coinbase_trader: trading engine (will log to /app/logs/coinbase_trader.py.log)
if [ -f ./coinbase_trader.py ]; then
  start_bg "python ./coinbase_trader.py" "$LOGDIR/coinbase_trader.py.log"
else
  echo "$(timestamp) [warn] coinbase_trader.py not found, skipping"
fi

# tv_webhook_listener - if it is a non-ASGI worker helper, keep it as background (optional)
# Uncomment this if you want tv_webhook_listener to run separately as a worker process.
# if [ -f ./tv_webhook_listener.py ]; then
#   start_bg "python ./tv_webhook_listener.py" "$LOGDIR/tv_webhook_listener.py.log"
# fi

# main.py - optional background process if it contains tasks you want running
if [ -f ./main.py ]; then
  start_bg "python ./main.py" "$LOGDIR/main.py.log"
fi

echo "$(timestamp) [inf] start_all.sh: launching web process in foreground"

# Exec uvicorn web server (this replaces python -m http.server fallback)
# web_app:app will import tv_webhook_listener.app if present, otherwise expose /webhook.
exec uvicorn web_app:app --host 0.0.0.0 --port "$PORT" --log-level info
