#!/bin/bash
echo "🌟 Starting Nija bot as background worker..."

# Make sure environment variables are set
echo "DEBUG: COINBASE_API_KEY=$COINBASE_API_KEY"
echo "DEBUG: COINBASE_API_SECRET=$COINBASE_API_SECRET"
echo "DEBUG: COINBASE_API_PASSPHRASE=$COINBASE_API_PASSPHRASE"
echo "DEBUG: API_PEM_B64=${API_PEM_B64:0:10}..."  # first 10 chars for sanity check

# Export PEM for Python
export API_PEM_B64="$API_PEM_B64"

# Activate virtual environment if needed
# source .venv/bin/activate

# Run the bot
python3 nija_live_snapshot.py
