#!/bin/sh
# Default to 5000 if $PORT is not set
PORT=${PORT:-5000}

echo "🌐 Starting Nija bot on port $PORT..."
exec gunicorn -w 1 -b 0.0.0.0:$PORT nija_bot_web:app
