#!/bin/bash
# ========================
# start_all.sh
# ========================

# Exit immediately if a command fails
set -e

echo "[INFO] Running pre-flight checks..."
python3 nija_client.py

echo "[INFO] Starting Nija Trading Bot in background..."
# Run the trading bot in the background
python3 nija_client.py &

echo "[INFO] Starting Flask App with Gunicorn..."
# Run Flask/Gunicorn in foreground (container keeps running)
exec gunicorn -w 2 -k gthread --threads 2 -b 0.0.0.0:5000 app:app
