#!/usr/bin/env bash
set -euo pipefail

# =========================
# Configuration
# =========================

# Gunicorn debug logging
export GUNICORN_CMD_ARGS="--log-level debug --error-logfile -"

# Default PORT if Railway doesn't provide one
PORT=${PORT:-5000}

# Log directory
LOG_DIR=/app/logs
mkdir -p "$LOG_DIR"

# =========================
# Start background bots
# =========================

echo "Starting background workers..."

# TV Webhook Listener
echo "[INFO] Starting tv_webhook_listener.py..."
nohup python tv_webhook_listener.py >> "$LOG_DIR/tv_webhook_listener.log" 2>&1 &

# Coinbase Trader
echo "[INFO] Starting coinbase_trader.py..."
nohup python coinbase_trader.py >> "$LOG_DIR/coinbase_trader.log" 2>&1 &

# =========================
# Start web app (Gunicorn)
# =========================

echo "[INFO] Starting web app on port $PORT..."
exec gunicorn web:app --bind 0.0.0.0:"$PORT"
