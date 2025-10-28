#!/usr/bin/env bash
echo "🌟 Starting Nija bot..."
# Ensure API keys are loaded in the environment
export COINBASE_API_KEY=${COINBASE_API_KEY:?COINBASE_API_KEY not set}
export COINBASE_API_SECRET=${COINBASE_API_SECRET:?COINBASE_API_SECRET not set}
export COINBASE_API_PASSPHRASE=${COINBASE_API_PASSPHRASE:-}

python3 nija_live_snapshot.py
