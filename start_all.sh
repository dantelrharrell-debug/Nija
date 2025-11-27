#!/bin/bash
# Ensure the script is executable: chmod +x start_all.sh

# Load environment variables
export $(grep -v '^#' .env | xargs)

# Start Flask app in the background
echo "=== Starting Flask App... ==="
gunicorn -w 2 -k gthread --threads 2 -b 0.0.0.0:5000 app:app &

# Start Nija Trading Bot with auto-restart
echo "=== Starting Nija Trading Bot... ==="
while true; do
    python3 nija_client.py || echo "Bot crashed! Restarting..."
    sleep 2
done
