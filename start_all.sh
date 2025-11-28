#!/usr/bin/env bash
# start_all.sh - entrypoint for container
set -euo pipefail

echo "$(date -u) | INFO | Starting NIJA (embedded script)"

# run quick connection test; if it fails, still print logs and continue (so container doesn't crash repeatedly)
python test_coinbase_connection.py || echo "$(date -u) | WARN | Coinbase connection test failed (see above). Continuing to start app."

# start gunicorn serving the Flask app
exec gunicorn --bind 0.0.0.0:5000 --workers 2 --timeout 120 "app:app"
