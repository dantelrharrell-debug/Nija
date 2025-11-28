#!/usr/bin/env bash
set -euo pipefail

echo "$(date -u) | INFO | Starting NIJA entrypoint"

# Optional: quick health check - will not crash container on failure
python test_coinbase_connection.py || echo "$(date -u) | WARN | coinbase test failed"

# Launch gunicorn, explicitly point at Flask instance in app.py
exec gunicorn --bind 0.0.0.0:8080 --workers 2 --threads 2 --timeout 120 app:app
