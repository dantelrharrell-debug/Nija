#!/bin/sh
# start_all.sh
echo "=== STARTING NIJA TRADING BOT ==="

# Start Gunicorn pointing to the Flask app
exec gunicorn --bind 0.0.0.0:8080 app:app
