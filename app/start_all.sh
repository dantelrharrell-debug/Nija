#!/usr/bin/env bash
set -euo pipefail

echo "[inf] === STARTING NIJA TRADING BOT CONTAINER ==="
date

mkdir -p /app/logs

# We assume deps installed at build time. If you intentionally want runtime installs,
# uncomment next line (not recommended).
# python3 -m pip install -r /app/requirements.txt --no-cache-dir

# Quick env checks (will error if missing)
: "${COINBASE_API_KEY:?Need COINBASE_API_KEY}"
: "${COINBASE_API_SECRET:?Need COINBASE_API_SECRET}"
: "${COINBASE_API_SUB:?Need COINBASE_API_SUB}"
echo "[INFO] All required environment variables are present."

echo "[INFO] Testing Coinbase connection..."
python3 - <<'PY'
from nija_client import test_coinbase_connection
import sys, logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
ok = test_coinbase_connection()
if not ok:
    print("[WARN] Coinbase connection test failed. Continuing startup but DISABLING live trading worker.")
    sys.exit(2)
print("[INFO] Coinbase connection test passed.")
sys.exit(0)
PY

RET=$?
if [ "$RET" -eq 0 ]; then
  echo "[INFO] Coinbase ready -> starting all workers including coinbase_trader."
  nohup python3 /app/tv_webhook_listener.py >> /app/logs/tv_webhook_listener.log 2>&1 &
  nohup python3 /app/coinbase_trader.py >> /app/logs/coinbase_trader.log 2>&1 &
else
  echo "[WARN] Coinbase not ready -> starting only non-trading workers."
  nohup python3 /app/tv_webhook_listener.py >> /app/logs/tv_webhook_listener.log 2>&1 &
  echo "[WARN] Live trading disabled. Check /app/logs/coinbase_module_debug.txt for details."
fi

echo "[INFO] Launching Gunicorn..."
exec gunicorn -c /app/gunicorn.conf.py web.wsgi:app
