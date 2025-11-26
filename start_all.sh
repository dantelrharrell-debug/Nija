#!/usr/bin/env bash
set -eo pipefail

echo "[INFO] === STARTING NIJA TRADING BOT CONTAINER ==="
date

# Install step is no-op if dependencies already installed at build time;
# left here so a dev container can still stand up if needed.
echo "[INFO] Installing Python dependencies (no-op if already installed at build time)..."
python3 -m pip install --upgrade pip setuptools wheel >/dev/null 2>&1 || true
python3 -m pip install --no-cache-dir -r /app/requirements.txt >/dev/null 2>&1 || true

# Ensure logs dir
mkdir -p /app/logs

# Run a single non-blocking Coinbase connection test (does not exit container)
echo "[INFO] Running single Coinbase connection test (will NOT block workers)..."
python3 - <<'PY'
import logging, os
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("startup_test")

try:
    from nija_client import test_coinbase_connection
except Exception as e:
    logger.warning("nija_client import failed: %s", e)
    test_coinbase_connection = lambda: False

result = False
try:
    result = test_coinbase_connection()
except Exception as e:
    logger.warning("Coinbase test raised: %s", e)

logger.info("Coinbase test result: %s", "success" if result else "failure")
# create debug file if failed
if not result:
    os.makedirs("/app/logs", exist_ok=True)
    with open("/app/logs/coinbase_module_debug.txt", "w") as f:
        f.write("Coinbase test failed at startup. See logs.\n")
PY

echo "[INFO] Starting background workers (if present)..."
# start background workers non-blocking (only if present)
[ -f /app/tv_webhook_listener.py ] && python3 /app/tv_webhook_listener.py >> /app/logs/tv_webhook_listener.log 2>&1 &
[ -f /app/coinbase_trader.py ] && python3 /app/coinbase_trader.py >> /app/logs/coinbase_trader.log 2>&1 &

echo "[INFO] Launching Gunicorn..."
exec gunicorn -b 0.0.0.0:5000 web.wsgi:app
