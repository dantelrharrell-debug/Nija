#!/bin/bash

# Exit on any error
set -e

# Print all commands for debugging
set -x

echo "🌟 Starting Nija bot..."

# Export API keys from environment (ensure these are set in Render)
export COINBASE_API_KEY="${COINBASE_API_KEY}"
export COINBASE_API_SECRET="${COINBASE_API_SECRET}"
export COINBASE_API_PASSPHRASE="${COINBASE_API_PASSPHRASE:-}"

# Debug output to confirm keys are loaded (don't log secrets in production)
echo "DEBUG: COINBASE_API_KEY=${COINBASE_API_KEY}"
echo "DEBUG: COINBASE_API_SECRET=${COINBASE_API_SECRET}"
echo "DEBUG: COINBASE_API_PASSPHRASE=${COINBASE_API_PASSPHRASE}"

# Run the bot in Python
python3 nija_live_snapshot.py
