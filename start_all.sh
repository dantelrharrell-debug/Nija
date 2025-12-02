#!/usr/bin/env bash
set -euo pipefail

echo "Starting NIJA Trading Bot orchestrator..."
echo "LIVE_TRADING=${LIVE_TRADING:-0}"

# Example: run any preflight checks
if [ -f ./pre_start.sh ]; then
  echo "Running pre_start.sh"
  ./pre_start.sh
fi

# Make sure the bot script exists
if [ -f ./start.sh ]; then
  echo "Launching start.sh"
  exec ./start.sh
fi

# Fallback: try to run the main bot entrypoint if present
if [ -f ./bot/live_trading.py ]; then
  echo "Running python bot/live_trading.py"
  exec python ./bot/live_trading.py
fi

echo "No start script found. Exiting."
exit 1
