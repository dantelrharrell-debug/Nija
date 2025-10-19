#!/bin/bash
# Auto-start WebSocket trading bot in background and run Gunicorn for the dashboard.

# If you use a virtualenv called .venv, activate it:
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
fi

# Start WebSocket bot in background
python nija_bot_ws.py &

# Start Flask dashboard via Gunicorn (foreground process keeps container alive)
exec gunicorn nija_bot_web:app --bind 0.0.0.0:$PORT
