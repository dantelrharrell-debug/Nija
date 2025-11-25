#!/bin/bash
set -e

echo "=== STARTING NIJA ==="

# Upgrade pip and install dependencies
python3 -m pip install --upgrade pip setuptools wheel
python3 -m pip install --no-cache-dir -r requirements.txt

# Initial Coinbase connection test
python3 - <<'PY'
from nija_client import test_coinbase_connection
test_coinbase_connection()
PY

# Start Gunicorn in the background
echo "Starting Gunicorn..."
gunicorn main:app \
    --bind 0.0.0.0:5000 \
    --workers 1 \
    --threads 2 \
    --timeout 120 \
    --log-level info &

GUNICORN_PID=$!
echo "Gunicorn PID: $GUNICORN_PID"

# Function to check Coinbase connection every minute
check_coinbase_loop() {
    while true; do
        python3 - <<'PY'
from nija_client import test_coinbase_connection
test_coinbase_connection()
PY
        sleep 60  # wait 1 minute
    done
}

# Run the health check loop in the background
check_coinbase_loop &
HEALTH_PID=$!
echo "Coinbase health check PID: $HEALTH_PID"

# Wait for Gunicorn to exit (keep container alive)
wait $GUNICORN_PID
