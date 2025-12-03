#!/usr/bin/env bash
set -euo pipefail

# Start the web app with gunicorn in background and start bot script in foreground
# Adjust paths to your start scripts as necessary.

PORT="${PORT:-8080}"
GUNICORN_CONFIG="./gunicorn.conf.py"

# Start Gunicorn (background)
echo "Starting Gunicorn on :${PORT}..."
gunicorn --config "${GUNICORN_CONFIG}" web.wsgi:application &

# Start bot as a separate process (foreground). Adjust module path if different.
echo "Starting NIJA bot process..."
# Example: python -m bot.live_bot_script
python -u bot/live_bot_script.py
