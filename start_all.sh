#!/usr/bin/env bash
set -euo pipefail

echo "[INFO] === STARTING NIJA TRADING BOT CONTAINER ==="
date

# Create logs folder
mkdir -p /app/logs

# Environment variable check (log, but do not exit)
: "${COINBASE_API_KEY:=""}"
: "${COINBASE_API_SECRET:=""}"
: "${COINBASE_API_SUB:=""}"

echo "[INFO] Starting background workers (if present)..."
# spawn workers if present
if [ -f /app/tv_webhook_listener.py ]; then
    nohup python3 /app/tv_webhook_listener.py >> /app/logs/tv_webhook_listener.log 2>&1 &
fi

if [ -f /app/coinbase_trader.py ]; then
    nohup python3 /app/coinbase_trader.py >> /app/logs/coinbase_trader.log 2>&1 &
fi

echo "[INFO] Launching Gunicorn..."
# Adjust module path to whatever your app uses; default below is web.wsgi:app
exec gunicorn -b 0.0.0.0:5000 web.wsgi:app
