#!/usr/bin/env bash
# start.sh — launch the Nija bot on Render

# Exit on any error
set -e

echo "🌟 Starting Nija bot..."

# Ensure required environment variables are present
: "${COINBASE_API_KEY:?COINBASE_API_KEY not set}"
: "${COINBASE_API_SECRET:?COINBASE_API_SECRET not set}"
: "${GITHUB_TOKEN:?GITHUB_TOKEN not set}"
: "${RENDER_API_KEY:?RENDER_API_KEY not set}"
: "${RAILWAY_API_KEY:?RAILWAY_API_KEY not set}"
: "${BOT_SECRET_KEY:?BOT_SECRET_KEY not set}"

# Set health port default if not provided
export HEALTH_PORT="${HEALTH_PORT:-10000}"
export DRY_RUN="${DRY_RUN:-False}"
export LOG_LEVEL="${LOG_LEVEL:-INFO}"

# Ensure run_trader.py is executable
chmod +x run_trader.py

# Launch the bot
exec python3 run_trader.py
