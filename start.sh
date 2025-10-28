#!/bin/bash
# ========================================
# start.sh for Nija bot (Render / Railway)
# ========================================

echo "🌟 Starting Nija bot..."

# No need to set API keys manually — they are injected by the platform
# Just check if they exist for safety
if [ -z "$COINBASE_API_KEY" ] || [ -z "$COINBASE_API_SECRET" ]; then
    echo "⚠️ Coinbase API keys not set! Bot will run in stub mode."
else
    echo "🔹 Coinbase API keys detected — live trading enabled."
fi

# Run the Python bot
python3 nija_live_snapshot.py
