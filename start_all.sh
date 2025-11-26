#!/usr/bin/env bash
set -euo pipefail

echo "=== STARTING NIJA TRADING BOT CONTAINER ==="
date

WSGI_MODULE="${WSGI_MODULE:-web.wsgi:app}"
PORT="${PORT:-5000}"
LOG_DIR="/app/logs"
mkdir -p "$LOG_DIR"

echo "[INFO] WSGI_MODULE='$WSGI_MODULE'  PORT='$PORT'"

# Install dependencies if requirements.txt exists
if [ -f "/app/requirements.txt" ]; then
  echo "[INFO] Installing Python dependencies..."
  pip install --upgrade pip setuptools wheel
  pip install -r /app/requirements.txt
fi

# Environment checks
echo "[ENV] COINBASE_API_KEY set? ${COINBASE_API_KEY:+yes}"
echo "[ENV] COINBASE_API_SECRET set? ${COINBASE_API_SECRET:+yes}"
echo "[ENV] COINBASE_API_SUB set? ${COINBASE_API_SUB:+yes}"

# Start background workers safely
for worker in tv_webhook_listener coinbase_trader; do
  echo "[INFO] Starting $worker (logs -> $LOG_DIR/$worker.log)..."
  nohup python -m "bots.$worker" >> "$LOG_DIR/$worker.log" 2>&1 &
done

sleep 0.5
echo "[INFO] Background workers started."

# Start Gunicorn
echo "[INFO] Launching Gunicorn on 0.0.0.0:$PORT..."
exec gunicorn "$WSGI_MODULE" --bind "0.0.0.0:$PORT" --workers 1 --threads 1 --timeout 30 --log-level debug --error-logfile -
