#!/bin/bash
# Run NIJA in LIVE Trading Mode (Real Money)

echo "💰 Starting NIJA in LIVE TRADING mode (REAL MONEY)"
echo "=================================================="
echo ""
echo "⚠️  WARNING: This will execute REAL trades on Coinbase"
echo "⚠️  Real money will be used"
echo ""
read -p "Type 'YES' to confirm: " confirmation

if [ "$confirmation" != "YES" ]; then
    echo "❌ Cancelled"
    exit 1
fi

export PAPER_MODE=false
python3 bot.py
