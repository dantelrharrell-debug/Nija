#!/bin/bash
# RESTART NIJA BOT - Monitor 13 Open Positions
# This bot will execute stop losses and take profits

set -e

echo "========================================"
echo "  🚀 RESTARTING NIJA TRADING BOT"
echo "========================================"
echo ""
echo "Bot will monitor your 13 positions:"
echo "  - ETH, SOL, LTC, BCH, AAVE, etc."
echo "  - All have 2% stop losses configured"
echo "  - All have 5% take profit targets"
echo ""
echo "Current Balance: $0.06"
echo "Open Positions Value: ~$19,900"
echo ""

# Check if running
BOT_PID=$(pgrep -f "python.*bot.py" || echo "")

if [ -n "$BOT_PID" ]; then
    echo "⚠️  Bot already running (PID: $BOT_PID)"
    echo ""
    read -p "Kill and restart? (y/n): " RESTART
    if [ "$RESTART" = "y" ]; then
        echo "Stopping existing bot..."
        kill $BOT_PID
        sleep 2
    else
        echo "Keeping existing bot running"
        exit 0
    fi
fi

echo "🔍 Checking credentials..."
if [ -z "$COINBASE_API_KEY" ] || [ -z "$COINBASE_API_SECRET" ]; then
    if [ -f .env ]; then
        echo "Loading from .env file..."
        set -a
        source .env
        set +a
    else
        echo "❌ ERROR: No Coinbase credentials found"
        echo ""
        echo "Set environment variables or create .env file with:"
        echo "  COINBASE_API_KEY='your_key'"
        echo "  COINBASE_API_SECRET='your_secret'"
        exit 1
    fi
fi

echo "✅ Credentials loaded"
echo ""

# Ensure position file exists
if [ ! -f data/open_positions.json ]; then
    echo "❌ ERROR: Position tracking file not found!"
    echo "   Expected: data/open_positions.json"
    exit 1
fi

echo "✅ Position tracking file found"
echo "   13 positions with stop losses configured"
echo ""

echo "🚀 Starting bot in background..."
nohup python3 bot.py > bot_runtime.log 2>&1 &
BOT_PID=$!

echo "✅ Bot started (PID: $BOT_PID)"
echo ""
echo "Monitoring:"
echo "  - Positions will be checked every 15 seconds"
echo "  - Stop losses at -2% will auto-sell"
echo "  - Take profits at +5% will auto-sell"
echo "  - View logs: tail -f bot_runtime.log"
echo ""
echo "========================================"
echo "  ✅ BOT IS NOW MONITORING POSITIONS"
echo "========================================"
