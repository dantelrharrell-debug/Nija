#!/bin/bash
echo "🌟 Starting Nija bot..."

# Optional: set PORT from environment
export HEALTH_PORT=${PORT:-8080}

# Ensure environment variables exist
if [ -z "$COINBASE_API_KEY" ] || [ -z "$COINBASE_API_SECRET" ]; then
    echo "⚠️ Coinbase API keys not set!"
    exit 1
fi

python3 nija_live_snapshot.py
