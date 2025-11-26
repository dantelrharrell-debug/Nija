#!/usr/bin/env bash
set -euo pipefail

echo "[inf] === STARTING NIJA TRADING BOT CONTAINER ==="
date
mkdir -p /app/logs

# We assume deps installed at build time via Dockerfile.
# Start a lightweight background monitor that writes debug info repeatedly.
echo "[inf] Launching coinbase monitor (background)..."
nohup python3 /app/coinbase_monitor.py >> /app/logs/coinbase_monitor.log 2>&1 &

# Start non-trading workers unconditionally (so container is useful)
echo "[inf] Starting non-trading workers..."
nohup python3 /app/tv_webhook_listener.py >> /app/logs/tv_webhook_listener.log 2>&1 &

# Do NOT start coinbase_trader automatically. It will be started later
# only after we confirm the correct client import name.
echo "[warn] Live trading worker is disabled until we confirm Coinbase client."

# Start Gunicorn so the web UI stays up
echo "[inf] Launching Gunicorn (web) on 0.0.0.0:${PORT:-8080}..."
exec gunicorn -c /app/gunicorn.conf.py web.wsgi:app
