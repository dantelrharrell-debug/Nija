#!/bin/bash
# Quick connection and restart script

echo "================================================"
echo "NIJA - CONNECTION TEST & BOT RESTART"
echo "================================================"
echo ""

# Activate venv
source .venv/bin/activate

# Test connection
echo "1️⃣ Testing Coinbase API connection..."
python -u VERIFY_API_CONNECTION.py

if [ $? -eq 0 ]; then
    echo ""
    echo "✅ CONNECTION SUCCESSFUL!"
    echo ""
    echo "2️⃣ Starting bot in LIVE MODE..."
    
    # Kill any existing bot
    pkill -f bot.py || true
    sleep 1
    
    # Start bot
    export PAPER_MODE=false
    export ALLOW_CONSUMER_USD=true
    
    ./start.sh
else
    echo ""
    echo "❌ CONNECTION FAILED - Bot not started"
    echo "   Check credentials in .env file"
fi
