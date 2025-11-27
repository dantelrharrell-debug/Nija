#!/bin/bash
# ----------------------
# Start All Script for Nija Trading Bot
# ----------------------

# Function to start the trading bot in a loop
start_bot() {
  while true; do
    echo "Starting Nija Trading Bot..."
    python3 nija_client.py
    echo "Bot crashed or stopped! Restarting in 2 seconds..."
    sleep 2
  done
}

# Start the trading bot in the background
start_bot &

# Start the Flask app with Gunicorn
echo "Starting Flask App..."
exec gunicorn -w 2 -k gthread --threads 2 -b 0.0.0.0:5000 app:app
