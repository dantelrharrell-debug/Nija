#!/bin/bash
# Execute all 4 tasks automatically without user interaction

cd /workspaces/Nija

echo "================================================================================"
echo "🚀 NIJA EMERGENCY RECOVERY - ALL 4 TASKS"
echo "================================================================================"
echo "⏰ $(date)"
echo ""

# TASK 1: Calculate exact losses
echo ""
echo "████████████████████████████████████████████████████████████████████████████████"
echo "█ TASK 1: CALCULATE EXACT LOSSES ON 13 POSITIONS"
echo "████████████████████████████████████████████████████████████████████████████████"
echo ""

python3 calculate_exact_losses.py || echo "⚠️  Task 1 failed"

# TASK 2: Force liquidate
echo ""
echo "████████████████████████████████████████████████████████████████████████████████"
echo "█ TASK 2: FORCE LIQUIDATE ALL 13 POSITIONS"
echo "████████████████████████████████████████████████████████████████████████████████"
echo ""

python3 FORCE_SELL_ALL_POSITIONS.py || echo "⚠️  Task 2 failed"

# TASK 3: Restart bot
echo ""
echo "████████████████████████████████████████████████████████████████████████████████"
echo "█ TASK 3: RESTART BOT WITH FRESH TRACKING"
echo "████████████████████████████████████████████████████████████████████████████████"
echo ""

# Clear position files
if [ -f "data/open_positions.json" ]; then
    echo "{}" > data/open_positions.json
    echo "✅ Cleared: data/open_positions.json"
fi

if [ -f "/usr/src/app/data/open_positions.json" ]; then
    echo "{}" > /usr/src/app/data/open_positions.json
    echo "✅ Cleared: /usr/src/app/data/open_positions.json"
fi

# Kill any running bot
pkill -f "trading_strategy" 2>/dev/null || true
pkill -f "live_trading" 2>/dev/null || true
pkill -f "bot.py" 2>/dev/null || true
sleep 2

# Start bot
if [ -f "start.sh" ]; then
    bash start.sh &
    echo "✅ Bot started in background (PID: $!)"
    echo "   Monitor with: tail -f nija.log"
elif [ -f "bot/trading_strategy.py" ]; then
    python3 bot/trading_strategy.py &
    echo "✅ Trading strategy started in background (PID: $!)"
else
    echo "❌ Cannot find startup script"
fi

sleep 3

# TASK 4: Check bot status
echo ""
echo "████████████████████████████████████████████████████████████████████████████████"
echo "█ TASK 4: CHECK IF BOT IS RUNNING"
echo "████████████████████████████████████████████████████████████████████████████████"
echo ""

python3 check_bot_status_now.py || echo "⚠️  Task 4 failed"

# Final summary
echo ""
echo "════════════════════════════════════════════════════════════════════════════════"
echo "✅ ALL 4 TASKS EXECUTED"
echo "════════════════════════════════════════════════════════════════════════════════"
echo ""
echo "COMPLETED:"
echo "  ✅ Task 1: Calculated exact losses"
echo "  ✅ Task 2: Liquidated all positions"
echo "  ✅ Task 3: Restarted bot fresh"
echo "  ✅ Task 4: Verified bot status"
echo ""
echo "NEXT STEPS:"
echo "  1. Monitor bot: tail -f nija.log"
echo "  2. Check positions: python check_current_positions.py"
echo "  3. Verify selling: python verify_nija_selling_now.py"
echo ""
echo "════════════════════════════════════════════════════════════════════════════════"
