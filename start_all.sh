#!/usr/bin/env bash
set -euo pipefail

echo "$(date -u) | INFO | Starting NIJA entrypoint"

# Optional non-fatal connectivity test (keeps container alive even if it fails)
python test_coinbase_connection.py || echo "$(date -u) | WARN | coinbase test failed"

# Explicitly point gunicorn at the Flask WSGI app (module:object).
# This assumes your Flask app file is 'app.py' and your Flask instance is named 'app'.
exec gunicorn -c gunicorn.conf.py app:app
