#!/bin/bash
set -e  # Exit immediately if a command exits with a non-zero status

echo "=== STARTING NIJA TRADING BOT CONTAINER ==="
echo "$(date)"

# ----------------------------
# 1️⃣ Install Python dependencies
# ----------------------------
echo "[INFO] Installing Python dependencies..."
pip install --upgrade pip setuptools wheel
pip install -r /app/requirements.txt --quiet

# ----------------------------
# 2️⃣ Check environment variables
# ----------------------------
: "${COINBASE_API_KEY:?Need to set COINBASE_API_KEY}"
: "${COINBASE_API_SECRET:?Need to set COINBASE_API_SECRET}"
: "${COINBASE_API_SUB:?Need to set COINBASE_API_SUB}"

echo "[INFO] All required environment variables are set."

# ----------------------------
# 3️⃣ Test Coinbase client
# ----------------------------
echo "[INFO] Testing Coinbase connection..."
python3 - <<END
from nija_client import test_coinbase_connection
if not test_coinbase_connection():
    print("[ERROR] Coinbase connection test failed. Exiting container.")
    exit(1)
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
