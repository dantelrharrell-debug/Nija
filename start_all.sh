#!/usr/bin/env bash
set -euo pipefail
echo "$(date -u) | INFO | Starting NIJA (entrypoint)"

# run the optional connection test but don't crash container on fail
python test_coinbase_connection.py || echo "WARN: coinbase test failed"

# Important: point gunicorn at the correct module:attribute
# If your file is app.py and Flask instance variable is `app`, use app:app
exec gunicorn --bind 0.0.0.0:8080 --workers 2 --threads 2 --timeout 120 app:app
