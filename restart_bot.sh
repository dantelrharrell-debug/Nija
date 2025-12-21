#!/bin/bash
# Restart bot with get_market_data fix

echo "🔄 Stopping current bot process..."
pkill -f "python3 run_bot.py"
sleep 2

echo "🚀 Starting bot with position management fix..."
cd /workspaces/Nija
python3 run_bot.py
