#!/bin/bash
set -e  # Exit on error

echo "=============================="
echo "    STARTING NIJA TRADING BOT"
echo "=============================="

python3 --version

# Test Coinbase module
python3 -c "from coinbase.rest import RESTClient; print('✅ Coinbase REST client available')"

echo "🔄 Starting live trading bot..."
echo "Working directory: $(pwd)"
echo "Bot file exists: $(test -f ./bot/live_trading.py && echo 'YES' || echo 'NO')"

# Start bot with full error output
python3 -u ./bot/live_trading.py 2>&1 || {
    echo "❌ Bot crashed! Exit code: $?"
    exit 1
}
