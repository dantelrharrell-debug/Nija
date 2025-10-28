#!/usr/bin/env bash
# start.sh — Launch Nija bot with environment variables

# Exit on any error
set -e

echo "🌟 Starting Nija bot in LIVE mode..."

# Use PORT provided by Render/Railway
export HEALTH_PORT="${PORT:-10000}"
export FLASK_RUN_PORT="${PORT:-10000}"

echo "🔹 Health server running on port $HEALTH_PORT"
echo "🔹 Flask server running on port $FLASK_RUN_PORT"

# Run the bot (live trading)
exec python3 run_trader.py
