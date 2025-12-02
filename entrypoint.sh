#!/bin/bash
set -e

# ---- Load environment variables from .env if it exists ----
if [ -f /usr/src/app/.env ]; then
    echo "[INFO] Loading environment variables from .env"
    export $(grep -v '^#' /usr/src/app/.env | xargs)
else
    echo "[WARNING] No .env file found. Make sure environment variables are set."
fi

# ---- Optional: Check required Coinbase variables ----
REQUIRED_VARS=("COINBASE_API_KEY" "COINBASE_API_SECRET" "COINBASE_API_PASSPHRASE")
for VAR in "${REQUIRED_VARS[@]}"; do
    if [ -z "${!VAR}" ]; then
        echo "[ERROR] Missing required environment variable: $VAR"
        exit 1
    fi
done

# ---- Start Gunicorn ----
echo "[INFO] Starting Gunicorn..."
exec gunicorn \
    --bind 0.0.0.0:5000 \
    --workers 2 \
    --threads 2 \
    --worker-class gthread \
    --timeout 120 \
    --preload \
    web.wsgi:app
