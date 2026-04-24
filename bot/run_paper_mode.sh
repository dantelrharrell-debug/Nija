#!/bin/bash
# Run NIJA in Paper Trading (Simulation) Mode

echo "📄 Starting NIJA in PAPER TRADING mode (Simulation)"
echo "=================================================="
echo ""
echo "✅ All trades will be simulated (no real money)"
echo "✅ Starting balance: \$10,000"
echo "✅ Tracks P&L in: paper_trading_data.json"
echo ""

export PAPER_MODE=true
python3 bot.py
