#!/usr/bin/env bash
# start.sh — Launch Nija bot on Render with all keys

# Exit on any error
set -e

echo "🌟 Starting Nija bot..."

# Ensure Python outputs logs immediately
export PYTHONUNBUFFERED=1

# Use the PORT from Render for health server
export HEALTH_PORT=${PORT:-10000}

# Logging and dry run
export DRY_RUN=${DRY_RUN:-False}
export LOG_LEVEL=${LOG_LEVEL:-INFO}

# Ensure all environment variables are present
: "${COINBASE_API_KEY:?COINBASE_API_KEY not set}"
: "${COINBASE_API_SECRET:?COINBASE_API_SECRET not set}"
: "${TV_WEBHOOK_SECRET:?TV_WEBHOOK_SECRET not set}"
: "${GITHUB_TOKEN:?GITHUB_TOKEN not set}"
: "${RENDER_API_KEY:?RENDER_API_KEY not set}"
: "${RAILWAY_API_KEY:?RAILWAY_API_KEY not set}"
: "${BOT_SECRET_KEY:?BOT_SECRET_KEY not set}"

# Ensure run_trader.py is executable
chmod +x run_trader.py

# Launch the bot
exec python3 run_trader.py
