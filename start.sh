#!/bin/bash
set -e

echo "Starting NIJA Trading Bot..."
echo "LIVE_TRADING=$LIVE_TRADING"

# Run the live trading script
python ./bot/live_trading.py
