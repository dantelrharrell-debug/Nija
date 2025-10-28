#!/bin/bash
set -e
set -o pipefail

echo "🌟 Starting Nija bot..."

# Print current environment for debugging
echo "COINBASE_API_KEY=$COINBASE_API_KEY"
echo "COINBASE_API_SECRET=$COINBASE_API_SECRET"
echo "COINBASE_API_PASSPHRASE=$COINBASE_API_PASSPHRASE"

# Function to run bot with auto-restart
run_bot() {
  while true; do
    # Only check for key + secret
    if [[ -z "$COINBASE_API_KEY" ]] || [[ -z "$COINBASE_API_SECRET" ]]; then
      echo "❌ ERROR: Coinbase API key/secret not set. Waiting 10 seconds..."
      sleep 10
      continue
    fi

    echo "🔁 Launching Nija bot..."
    python3 nija_live_snapshot.py 2>&1 | tee -a nija_bot.log

    echo "⚠️ Bot stopped unexpectedly. Restarting in 5 seconds..."
    sleep 5
  done
}

run_bot
