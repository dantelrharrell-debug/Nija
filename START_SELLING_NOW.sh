#!/bin/bash
# EMERGENCY FIX AND START - No questions, just DO IT
set -e

echo "╔════════════════════════════════════════════════════════════════════════════════╗"
echo "║           🚨 EMERGENCY MODE: FINDING MONEY + STARTING SELLS NOW 🚨            ║"
echo "╚════════════════════════════════════════════════════════════════════════════════╝"
echo ""

# Step 1: Quick balance check
echo "💰 Checking all accounts..."
python3 FIND_AND_FIX_NOW.py
echo ""

# Step 2: Enable Consumer USD
echo "⚙️  Enabling ALLOW_CONSUMER_USD=true..."
export ALLOW_CONSUMER_USD=true
echo "✅ Consumer USD enabled - bot can trade with ALL your funds"
echo ""

# Step 3: Start the bot immediately
echo "╔════════════════════════════════════════════════════════════════════════════════╗"
echo "║                     🚀 STARTING NIJA BOT IN 3 SECONDS...                       ║"
echo "╚════════════════════════════════════════════════════════════════════════════════╝"
echo ""
echo "Bot will:"
echo "  ✅ Scan markets every 2.5 minutes"
echo "  ✅ Auto-sell at +6% profit or -2% loss"
echo "  ✅ Trail stops to lock in gains"
echo "  ✅ Compound profits automatically"
echo ""

sleep 1
echo "3..."
sleep 1
echo "2..."
sleep 1
echo "1..."
sleep 1

echo ""
echo "🚀 LAUNCHING NOW!"
echo "═══════════════════════════════════════════════════════════════════════════════"
echo ""

# Start the bot
exec ./start.sh
