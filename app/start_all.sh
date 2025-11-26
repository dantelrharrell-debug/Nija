#!/usr/bin/env bash
set -e

echo "[INFO] === STARTING NIJA TRADING BOT CONTAINER ==="
date

echo "[INFO] Installing Python dependencies (no-op if built into image) ..."
# Avoid runtime installs here; dependencies should be installed at build time.
# If your platform has a build step, confirm requirements were installed at build time.

# Check required env vars; if missing, warn but continue so you can access debug endpoints.
if [ -z "${COINBASE_API_KEY}" ] || [ -z "${COINBASE_API_SECRET}" ]; then
  echo "[WARN] Coinbase API keys not fully set. Live trading will be disabled until keys are provided."
else
  echo "[INFO] Coinbase env vars appear set."
fi

echo "[INFO] Running single Coinbase connection test (non-blocking to workers)..."
python3 - <<'PY'
from nija_client import test_coinbase_connection
import logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
ok = test_coinbase_connection()
print("[INFO] Coinbase test result:", ok)
PY

echo "[INFO] Starting background workers (if present)..."
mkdir -p /app/logs

# Start optional background scripts if they exist (non-fatal)
if [ -f /app/tv_webhook_listener.py ]; then
  nohup python3 /app/tv_webhook_listener.py >> /app/logs/tv_webhook_listener.log 2>&1 &
  echo "[INFO] Started tv_webhook_listener.py"
fi

if [ -f /app/coinbase_trader.py ]; then
  nohup python3 /app/coinbase_trader.py >> /app/logs/coinbase_trader.log 2>&1 &
  echo "[INFO] Started coinbase_trader.py"
fi

echo "[INFO] Launching Gunicorn..."
# Ensure WEB entrypoint is correct for your repo. Common ones:
# - if app is app.py with Flask app variable:  app:app
# - if using web.wsgi: web.wsgi:app  (make sure web/wsgi.py defines 'app')
# Replace 'app:app' below with your correct module if different.
exec gunicorn -b 0.0.0.0:5000 app:app
