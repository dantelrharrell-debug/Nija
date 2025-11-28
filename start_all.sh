#!/bin/bash
set -e
echo "=== STARTING NIJA TRADING BOT ==="

# Ensure we're in /app (adjust if your working dir is different)
cd /app || true

# Optional: test Coinbase connection
python -c "from nija_client import test_coinbase_connection; test_coinbase_connection()"

# Run Flask app with gunicorn (production-ready)
# Uses 2 workers and 2 threads (adjust for your container resources)
if [ -f "app.py" ]; then
    echo "Starting Flask server via Gunicorn..."
    exec gunicorn --bind 0.0.0.0:8080 --workers 2 --threads 2 app:app
else
    echo "No Flask app.py found. Running in background mode only."
    # Keep container alive so threads in nija_client.py can run
    tail -f /dev/null
fi
