#!/bin/bash
# start.sh - Start Nija bot fully live

echo "🌟 Starting Nija bot..."

# Load environment variables (already set in Render/Railway)
export COINBASE_API_KEY=${COINBASE_API_KEY}
export COINBASE_API_SECRET=${COINBASE_API_SECRET}

# Ensure keys exist
if [[ -z "$COINBASE_API_KEY" || -z "$COINBASE_API_SECRET" ]]; then
    echo "❌ Coinbase API keys not detected. Set COINBASE_API_KEY and COINBASE_API_SECRET."
    exit 1
fi

echo "🔹 Coinbase API keys detected — live trading enabled."

# Run snapshot script to check accounts/status
python3 nija_live_snapshot.py
if [[ $? -ne 0 ]]; then
    echo "❌ Snapshot failed. Check Coinbase keys and nija_live_snapshot.py."
    exit 1
fi

# Start the trading loop
python3 nija_trading_loop.py
