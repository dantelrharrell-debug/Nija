#!/bin/bash
# Make sure this file is executable: chmod +x start_all.sh

echo "=== Starting Flask App... ==="
# Start Flask app in background
gunicorn -w 2 -k gthread --threads 2 -b 0.0.0.0:5000 app:app &

echo "=== Starting Nija Trading Bot... ==="
# Loop to restart bot on crash
while true; do
    python3 nija_client.py
    echo "Bot crashed or stopped! Restarting in 2 seconds..."
    sleep 2
done
