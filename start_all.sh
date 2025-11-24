#!/usr/bin/env bash
set -euo pipefail

# =========================
# Configuration
# =========================

PORT=${PORT:-5000}
LOG_DIR=/app/logs
mkdir -p "$LOG_DIR"

# =========================
# Start background bots
# =========================

echo "[INFO] Starting background workers..."

nohup python3 /app/bots/tv_webhook_listener.py >> "$LOG_DIR/tv_webhook_listener.log" 2>&1 &
nohup python3 /app/bots/coinbase_trader.py >> "$LOG_DIR/coinbase_trader.log" 2>&1 &

# =========================
# Start web app (Gunicorn)
# =========================

echo "[INFO] Starting web app on port $PORT..."
exec gunicorn web.wsgi:app --bind 0.0.0.0:"$PORT" --log-level debug --error-logfile -
