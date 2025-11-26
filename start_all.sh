#!/usr/bin/env bash
set -euo pipefail

echo "[INFO] === STARTING NIJA TRADING BOT CONTAINER ==="
date

echo "[INFO] Installing Python dependencies (no-op if already installed at build time)..."
# If you already install at build time in Dockerfile, this is safe to keep or remove.
python3 -m pip install --upgrade pip setuptools wheel >/dev/null 2>&1 || true
python3 -m pip install --no-cache-dir -r /app/requirements.txt >/dev/null 2>&1 || true

# Ensure logs dir
mkdir -p /app/logs
DEBUG_FILE="/app/logs/coinbase_module_debug.txt"

echo "[INFO] Running single Coinbase connection test (will NOT block workers)..."
python3 - <<PYCODE || RESULT=$?
import json, os
from nija_client import test_coinbase_connection
res = test_coinbase_connection()
# write a short debug file for the endpoint
with open("/app/logs/coinbase_module_debug.txt", "w") as f:
    f.write("coinbase_test_result: " + ("success" if res else "failure") + "\n")
print("[INFO] Coinbase test result:", "success" if res else "failure")
# do not exit non-zero — continue even if test failed
PYCODE

echo "[INFO] Starting background workers (if present)..."
# start optional background workers in background if files exist
if [ -f /app/tv_webhook_listener.py ]; then
  python3 /app/tv_webhook_listener.py >> /app/logs/tv_webhook_listener.log 2>&1 &
fi
if [ -f /app/coinbase_trader.py ]; then
  python3 /app/coinbase_trader.py >> /app/logs/coinbase_trader.log 2>&1 &
fi

echo "[INFO] Launching Gunicorn..."
# Adjust web target if your app path is different (app:app vs web.wsgi:app)
exec gunicorn -b 0.0.0.0:5000 web.wsgi:app
