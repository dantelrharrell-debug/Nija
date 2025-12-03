#!/bin/bash
echo "=============================="
echo "    STARTING NIJA TRADING BOT"
echo "=============================="

python3 --version

# Test Coinbase module
python3 -c "import coinbase_advanced_py; print('✅ coinbase_advanced_py found at', coinbase_advanced_py.__file__)"

# Start bot
python3 ./bot/live_trading.py
