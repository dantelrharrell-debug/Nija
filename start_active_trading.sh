#!/bin/bash

echo "═══════════════════════════════════════════════════════════════════"
echo "🎯 NIJA - ACTIVE TRADING MODE"
echo "═══════════════════════════════════════════════════════════════════"
echo ""
echo "✅ Configuration Updated:"
echo "   • Take Profit: 2-3% (was 5-8%)"
echo "   • Stop Loss: 1.5% (was 2%)"
echo "   • Max Positions: 3 (was 8)"
echo "   • Trailing: 90% lock (was 80%)"
echo "   • Cooldown: 60s (was 180s)"
echo ""
echo "═══════════════════════════════════════════════════════════════════"
echo ""

# Step 1: Clear any profitable positions
echo "Step 1: Checking for positions to clear..."
echo ""

if [ -f "clear_positions_take_profit.py" ]; then
    python clear_positions_take_profit.py
    echo ""
else
    echo "⚠️  Clear positions script not found, skipping..."
    echo ""
fi

# Step 2: Activate virtual environment
echo "Step 2: Activating Python environment..."
if [ -d ".venv" ]; then
    source .venv/bin/activate
    echo "✅ Virtual environment activated"
else
    echo "⚠️  No .venv found, using system Python"
fi
echo ""

# Step 3: Start the bot
echo "Step 3: Starting NIJA bot with active trading mode..."
echo ""
echo "═══════════════════════════════════════════════════════════════════"
echo "📊 NIJA IS NOW RUNNING IN ACTIVE TRADING MODE"
echo "═══════════════════════════════════════════════════════════════════"
echo ""
echo "What to expect:"
echo "  ✅ Quick exits at 2-3% profit"
echo "  ✅ Maximum 3 concurrent positions"
echo "  ✅ Faster position turnover"
echo "  ✅ Active compounding"
echo ""
echo "Monitor logs: tail -f nija.log"
echo "Stop bot: Ctrl+C"
echo ""
echo "═══════════════════════════════════════════════════════════════════"
echo ""

# Start the bot
if [ -f "bot/live_trading.py" ]; then
    python bot/live_trading.py
elif [ -f "start.sh" ]; then
    bash start.sh
else
    echo "❌ No start script found!"
    echo "Please run manually: python bot/live_trading.py"
fi
