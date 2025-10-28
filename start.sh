#!/usr/bin/env bash

echo "🌟 Starting Nija bot..."

# Safe environment variable checks
: "${COINBASE_API_KEY:?Warning: COINBASE_API_KEY not set, using stub client}"
: "${COINBASE_API_SECRET:?Warning: COINBASE_API_SECRET not set, using stub client}"
: "${GITHUB_TOKEN:?Warning: GITHUB_TOKEN not set, skipping GitHub features}"
: "${BOT_SECRET_KEY:?Warning: BOT_SECRET_KEY not set}"
: "${TV_WEBHOOK_SECRET:?Warning: TV_WEBHOOK_SECRET not set}"

# Set defaults for missing optional vars
: "${HEALTH_PORT:=10000}"

# Export if needed by Python scripts
export COINBASE_API_KEY
export COINBASE_API_SECRET
export GITHUB_TOKEN
export BOT_SECRET_KEY
export TV_WEBHOOK_SECRET
export HEALTH_PORT

echo "🔹 Health server will run on port $HEALTH_PORT"

# Run the bot
python3 -u run_trader.py
