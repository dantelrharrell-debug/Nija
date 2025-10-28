#!/bin/bash
set -e  # exit on first error
echo "🌟 Starting Nija bot..."

# Ensure virtual environment is active
if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

# Check required environment variables
if [ -z "$COINBASE_API_KEY" ] || [ -z "$COINBASE_API_SECRET" ]; then
    echo "❌ Missing Coinbase API_KEY or API_SECRET. Exiting."
    exit 1
fi

# Run the Python bot
python3 nija_live_snapshot.py
