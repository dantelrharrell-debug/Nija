#!/usr/bin/env bash
set -euo pipefail

LOG_DIR="/tmp/nija_logs"
mkdir -p "$LOG_DIR"
INSTALL_LOG="$LOG_DIR/coinbase_install.log"
WORKER_LOG="$LOG_DIR/nija_worker.log"
START_LOG="$LOG_DIR/start_all.log"

echo "== START_ALL.SH: Starting container ==" | tee -a "$START_LOG"

# Required env vars
required_vars=(GITHUB_PAT COINBASE_API_KEY COINBASE_API_SECRET)
missing=()
for v in "${required_vars[@]}"; do
  if [ -z "${!v:-}" ]; then
    missing+=("$v")
  fi
done

if [ "${#missing[@]}" -gt 0 ]; then
  echo "❌ ERROR: Missing required environment variables: ${missing[*]}" | tee -a "$START_LOG" "$INSTALL_LOG"
  exit 1
fi

# Install coinbase-advanced (retry loop)
echo "⏳ Installing coinbase-advanced (runtime)..." | tee -a "$INSTALL_LOG"
RETRIES=3
COUNT=0
SUCCESS=0
while [ $COUNT -lt $RETRIES ]; do
  COUNT=$((COUNT+1))
  echo "Attempt $COUNT of $RETRIES..." | tee -a "$INSTALL_LOG"
  python3 -m pip install --upgrade pip setuptools wheel >>"$INSTALL_LOG" 2>&1 || true
  if python3 -m pip install --no-cache-dir "git+https://${GITHUB_PAT}@github.com/coinbase/coinbase-advanced-python.git" >>"$INSTALL_LOG" 2>&1 ; then
    SUCCESS=1
    break
  else
    echo "Install attempt $COUNT failed. Sleeping before retry..." | tee -a "$INSTALL_LOG"
    sleep $((5 * COUNT))
  fi
done

if [ "$SUCCESS" -ne 1 ]; then
  echo "❌ Failed to install coinbase-advanced after $RETRIES attempts. See $INSTALL_LOG" | tee -a "$START_LOG"
  cat "$INSTALL_LOG" | sed -n '1,200p' >&2
  exit 1
fi

echo "✅ coinbase-advanced installed" | tee -a "$INSTALL_LOG" "$START_LOG"

# Start trading bot in background with automatic restart on crash
start_worker() {
  echo "$(date -u) ⚡ Starting trading worker (background)..." | tee -a "$WORKER_LOG" "$START_LOG"
  # run worker in a loop so it restarts if it dies
  while true; do
    python3 nija_render_worker.py >>"$WORKER_LOG" 2>&1 || {
      echo "$(date -u) 🚨 Worker crashed (exit code $?); restarting in 5s..." | tee -a "$WORKER_LOG"
      sleep 5
    }
  done &
  WORKER_PID=$!
  echo "Worker PID: $WORKER_PID" | tee -a "$WORKER_LOG" "$START_LOG"
}

stop_worker() {
  if [ -n "${WORKER_PID:-}" ]; then
    echo "$(date -u) Stopping worker (PID $WORKER_PID)" | tee -a "$START_LOG"
    kill "$WORKER_PID" 2>/dev/null || true
  fi
}

# Trap termination signals and stop background worker
trap 'echo "SIGTERM received, shutting down"; stop_worker; exit 0' SIGTERM SIGINT EXIT

start_worker

# Start Gunicorn (main process). Exec so container PID 1 is gunicorn.
echo "🚀 Starting Gunicorn (main web server)..." | tee -a "$START_LOG"
exec gunicorn -w 1 -b 0.0.0.0:5000 main:app --log-level info
