#!/bin/sh
# Ensure valid port
PORT=${PORT:-5000}  # Default to 5000 if not set
echo "🌐 Starting Nija on port $PORT..."
exec gunicorn -w 1 -b 0.0.0.0:$PORT nija_bot_web:app
