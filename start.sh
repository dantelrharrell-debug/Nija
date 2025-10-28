#!/bin/bash
echo "🌟 Starting Nija bot..."

# Export Coinbase keys from environment variables
export COINBASE_API_KEY=${COINBASE_API_KEY}
export COINBASE_API_SECRET=${COINBASE_API_SECRET}
export COINBASE_API_PASSPHRASE=${COINBASE_API_PASSPHRASE}

# Debug logging
echo "DEBUG: COINBASE_API_KEY=$COINBASE_API_KEY"
echo "DEBUG: COINBASE_API_SECRET=$COINBASE_API_SECRET"
echo "DEBUG: COINBASE_API_PASSPHRASE=$COINBASE_API_PASSPHRASE"

# Start the bot
python3 nija_live_snapshot.py
