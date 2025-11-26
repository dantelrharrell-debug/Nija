#!/usr/bin/env bash
set -e  # Exit immediately if any command fails (except our Coinbase check)

echo "[INFO] === STARTING NIJA TRADING BOT CONTAINER ==="
date

# ----------------------------
# 1️⃣ Install Python dependencies safely
# ----------------------------
echo "[INFO] Installing Python dependencies..."
python3 -m pip install --no-cache-dir --root-user-action=ignore --upgrade pip setuptools wheel
python3 -m pip install --no-cache-dir --root-user-action=ignore -r /app/requirements.txt

# ----------------------------
# 2️⃣ Check environment variables
# ----------------------------
: "${COINBASE_API_KEY:?Need to set COINBASE_API_KEY}"
: "${COINBASE_API_SECRET:?Need to set COINBASE_API_SECRET}"
: "${COINBASE_API_SUB:?Need to set COINBASE_API_SUB}"
echo "[INFO] All required environment variables are set."

# ----------------------------
# 3️⃣ Test Coinbase connection (non-fatal)
# ----------------------------
echo "[INFO] Testing Coinbase connection..."
python3 - <<END
from nija_client import test_coinbase_connection

if test_coinbase_connection():
    print("[INFO] Coinbase connection OK.")
else:
    print("[WARNING] Coinbase connection test failed. Continuing container startup.")
END

# ----------------------------
# 4️⃣ Start background workers
# ----------------------------
echo "[INFO] Starting background workers..."
mkdir -p /app/logs

python3 /app/tv_webhook_listener.py >> /app/logs/tv_webhook_listener.log 2>&1 &
python3 /app/coinbase_trader.py >> /app/logs/coinbase_trader.log 2>&1 &

echo "[INFO] Background workers started."

# ----------------------------
# 5️⃣ Launch Gunicorn web server
# ----------------------------
echo "[INFO] Launching Gunicorn..."
exec gunicorn -c /app/gunicorn.conf.py web.wsgi:app
