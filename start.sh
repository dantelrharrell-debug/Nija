echo "COINBASE_API_KEY=$COINBASE_API_KEY"
echo "COINBASE_API_SECRET=$COINBASE_API_SECRET"
echo "COINBASE_API_PASSPHRASE=$COINBASE_API_PASSPHRASE"

#!/bin/bash
set -e
set -o pipefail

echo "🌟 Starting Nija bot..."

# Check Coinbase API keys
if [[ -z "$COINBASE_API_KEY" ]] || [[ -z "$COINBASE_API_SECRET" ]] || [[ -z "$COINBASE_API_PASSPHRASE" ]]; then
  echo "❌ ERROR: Coinbase API keys not set!"
  exit 1
fi

# Function to run the bot with auto-restart
run_bot() {
  while true; do
    echo "🔁 Launching Nija bot..."
    python3 nija_live_snapshot.py 2>&1 | tee -a nija_bot.log

    echo "⚠️ Bot crashed or stopped unexpectedly. Restarting in 5 seconds..."
    sleep 5
  done
}

# Start bot
run_bot
