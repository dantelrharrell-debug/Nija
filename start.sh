#!/bin/bash
# start.sh - Start Nija bot safely with Coinbase API check

echo "🌟 Starting Nija bot..."

# Load environment variables (optional if already set in Render/Railway)
export COINBASE_API_KEY=${COINBASE_API_KEY}
export COINBASE_API_SECRET=${COINBASE_API_SECRET}

# Check if Coinbase API keys are set
if [[ -z "$COINBASE_API_KEY" || -z "$COINBASE_API_SECRET" ]]; then
    echo "❌ Coinbase API keys not detected. Set COINBASE_API_KEY and COINBASE_API_SECRET in environment variables."
    exit 1
fi

echo "🔹 Coinbase API keys detected — live trading enabled."

# Run the trading bot
python3 nija_live_snapshot.py

# Optionally, you can start the trading loop in the same script:
# python3 nija_trading_loop.py
