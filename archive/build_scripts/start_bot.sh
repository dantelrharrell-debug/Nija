#!/bin/bash
set -e

echo "=== STARTING NIJA TRADING BOT CONTAINER ==="

# 1️⃣ Install dependencies
echo "[INFO] Installing Python dependencies..."
pip install --upgrade pip
pip install -r requirements.txt

# 2️⃣ Check required environment variables
REQUIRED_VARS=("COINBASE_API_KEY" "COINBASE_API_SECRET" "COINBASE_API_PASSPHRASE")
for VAR in "${REQUIRED_VARS[@]}"; do
    if [ -z "${!VAR}" ]; then
        echo "[ERROR] Missing environment variable: $VAR"
        echo "Please set $VAR before running the bot."
        exit 1
    fi
done

echo "[INFO] All required environment variables are set."

# 3️⃣ Start Gunicorn with Flask app
echo "[INFO] Starting Gunicorn..."
exec gunicorn \
    --chdir /usr/src/app \
    --bind 0.0.0.0:5000 \
    --workers 2 \
    --threads 2 \
    --worker-class gthread \
    --log-level debug \
    --capture-output \
    web.wsgi:app
