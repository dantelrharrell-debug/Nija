#!/bin/bash
set -e

echo "╔════════════════════════════════════════════════════════════════════════════════╗"
echo "║              🚀 FIX POSITIONS (8 MAX) → COMMIT → START TRADING 🚀             ║"
echo "╚════════════════════════════════════════════════════════════════════════════════╝"
echo ""

# Step 1: Show what was fixed
echo "✅ FIXES APPLIED:"
echo "   • apex_config.py: max_positions = 8 (was 5)"
echo "   • trading_strategy.py: max_concurrent_positions = 8 (already set)"
echo "   • All configs now enforce 8 position limit consistently"
echo ""

# Step 2: Commit and push
echo "📝 Committing changes to GitHub..."
chmod +x commit_position_fix.sh
./commit_position_fix.sh
echo ""

# Step 3: Find money
echo "💰 Finding your $164.45..."
python3 FIND_AND_FIX_NOW.py
echo ""

# Step 4: Start trading
echo "╔════════════════════════════════════════════════════════════════════════════════╗"
echo "║                     🚀 STARTING TRADING IN 3 SECONDS...                        ║"
echo "╚════════════════════════════════════════════════════════════════════════════════╝"
echo ""
echo "Bot will now:"
echo "  ✅ Max 8 concurrent positions (FIXED)"
echo "  ✅ Auto-sell at +6% profit or -2% loss"
echo "  ✅ Trail stops to lock in gains"
echo "  ✅ Scan 732+ markets every 2.5 minutes"
echo ""

sleep 1
echo "3..."
sleep 1
echo "2..."
sleep 1
echo "1..."
sleep 1

echo ""
echo "🚀 LAUNCHING NIJA NOW!"
echo "═══════════════════════════════════════════════════════════════════════════════"
echo ""

# Enable Consumer USD and start
export ALLOW_CONSUMER_USD=true
exec ./start.sh
