#!/bin/sh
# start_all.sh
set -e

echo "=== STARTING NIJA TRADING BOT ==="

# Ensure we're in /app in case host differs
cd /app || true

# Use gunicorn to run the top-level app object inside app.py (module:attribute)
# -w 2 for a couple workers; adjust if you want
exec gunicorn --bind 0.0.0.0:8080 --workers 2 --threads 2 app:app
