#!/bin/bash
set -e

echo "╔════════════════════════════════════════════════════════════════════════════════╗"
echo "║                    🔧 FIND $164.45 → FIX ISSUE → START SELLING                ║"
echo "╚════════════════════════════════════════════════════════════════════════════════╝"
echo ""

# Step 1: Find the money
echo "📍 STEP 1: Finding your $164.45..."
echo "───────────────────────────────────────────────────────────────────────────────"
python3 FIND_AND_FIX_NOW.py
echo ""

# Ask user if they want to start trading
echo "╔════════════════════════════════════════════════════════════════════════════════╗"
echo "║                           🚀 READY TO START TRADING?                           ║"
echo "╚════════════════════════════════════════════════════════════════════════════════╝"
echo ""
echo "The bot will:"
echo "  ✅ Enable ALLOW_CONSUMER_USD=true (use all your funds)"
echo "  ✅ Scan 732+ cryptocurrency markets every 2.5 minutes"
echo "  ✅ Execute dual RSI strategy (RSI_9 + RSI_14)"
echo "  ✅ Auto-sell positions at:"
echo "     • +6% profit (take profit)"
echo "     • -2% loss (stop loss)"
echo "     • Trailing stops (lock in 98% of gains)"
echo "     • Opposite signals (exit on trend change)"
echo ""
read -p "Start NIJA trading bot now? (y/n): " -n 1 -r
echo ""

if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo ""
    echo "🚀 LAUNCHING NIJA TRADING BOT..."
    echo "───────────────────────────────────────────────────────────────────────────────"
    
    # Enable Consumer USD trading
    export ALLOW_CONSUMER_USD=true
    
    # Start the bot
    ./start.sh
else
    echo ""
    echo "⏸️  Bot start cancelled."
    echo ""
    echo "💡 When ready to trade, run:"
    echo "   ./start.sh"
    echo ""
    echo "   Or use this script again:"
    echo "   bash RUN_FIX_AND_START.sh"
    echo ""
fi
