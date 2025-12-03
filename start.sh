#!/bin/bash
echo "=============================="
echo "    STARTING NIJA TRADING BOT"
echo "=============================="

python3 --version

# Test if Coinbase module is visible
python3 -c "import coinbase_advanced_py; print('✅ coinbase_advanced_py found at', coinbase_advanced_py.__file__)"

# Launch your bot
python3 ./bot/live_trading.py
