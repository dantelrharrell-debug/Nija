#!/usr/bin/env bash
set -euo pipefail

echo "Starting NIJA Trading Bot..."
echo "LIVE_TRADING=${LIVE_TRADING:-0}"

# Activate any environment-specific commands (none here)
# Launch the python bot entrypoint (update path if your main runner is different)
if [ -f ./bot/live_trading.py ]; then
  exec python ./bot/live_trading.py
elif [ -f ./start_bot.sh ]; then
  exec ./start_bot.sh
else
  echo "ERROR: No bot entrypoint found (expected ./bot/live_trading.py or ./start_bot.sh)."
  exit 2
fi
