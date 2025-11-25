#!/bin/bash
set -e

echo "=== STARTING NIJA ==="

# Upgrade pip and install dependencies
python3 -m pip install --upgrade pip setuptools wheel
python3 -m pip install --no-cache-dir -r requirements.txt

# Test Coinbase connection before starting Gunicorn
python3 - <<'PY'
from nija_client import test_coinbase_connection
test_coinbase_connection()
PY

# Start Gunicorn with 1 worker and 2 threads
exec gunicorn main:app \
    --bind 0.0.0.0:5000 \
    --workers 1 \
    --threads 2 \
    --timeout 120 \
    --log-level info
