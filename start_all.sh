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

# Function to check Coinbase connection with exponential backoff
check_coinbase_loop() {
    backoff=5  # start with 5 seconds
    max_backoff=300  # max 5 minutes
    while true; do
        python3 - <<'PY'
from nija_client import test_coinbase_connection
success = test_coinbase_connection()
PY
        if [ $? -eq 0 ]; then
            # Reset backoff if connection succeeds
            backoff=5
        else
            # Increase backoff exponentially on failure
            echo "⚠️ Coinbase check failed. Retrying in $backoff seconds..."
            sleep $backoff
            backoff=$((backoff * 2))
            if [ $backoff -gt $max_backoff ]; then
                backoff=$max_backoff
            fi
            continue
        fi
        # Wait 60 seconds before next regular check
        sleep 60
    done
}

# Run the health check loop in the background
check_coinbase_loop &
HEALTH_PID=$!
echo "Coinbase health check PID: $HEALTH_PID"

# Wait for Gunicorn to exit (keeps container alive)
wait $GUNICORN_PID
