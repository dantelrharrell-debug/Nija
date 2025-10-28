#!/usr/bin/env bash
# start.sh — launch the trading bot on Render

# Fail on any error
set -e

# Ensure Python environment
export PYTHONUNBUFFERED=1

# Use the PORT from Render for health server
export HEALTH_PORT=${PORT:-10000}

# Log DRY_RUN (set to False for live)
export DRY_RUN=${DRY_RUN:-False}
export LOG_LEVEL=${LOG_LEVEL:-INFO}

# Ensure execute permissions
chmod +x run_trader.py

# Launch the bot
exec python3 run_trader.py
