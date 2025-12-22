#!/bin/bash
# Restart NIJA bot with bleeding fixes deployed

echo "╔════════════════════════════════════════════════════════════════╗"
echo "║     NIJA BOT RESTART - BLEEDING FIXES DEPLOYED                ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""

cd /workspaces/Nija

# Stop existing bot
echo "1. Stopping existing bot process..."
pkill -f "python.*bot.py" 2>/dev/null || echo "   No bot process found"
sleep 2

# Verify stopped
if pgrep -f "python.*bot.py" > /dev/null; then
    echo "   ⚠️  Bot still running, force killing..."
    pkill -9 -f "python.*bot.py"
    sleep 2
fi
echo "   ✅ Bot stopped"
echo ""

# Show git status
echo "2. Verifying fixes are in place..."
git log -1 --oneline | head -1
echo ""

# Check Python syntax
echo "3. Validating Python syntax..."
python3 -m py_compile bot/adaptive_growth_manager.py 2>&1
if [ $? -eq 0 ]; then
    echo "   ✅ adaptive_growth_manager.py syntax OK"
else
    echo "   ❌ SYNTAX ERROR in adaptive_growth_manager.py"
    exit 1
fi

python3 -m py_compile bot/trading_strategy.py 2>&1
if [ $? -eq 0 ]; then
    echo "   ✅ trading_strategy.py syntax OK"
else
    echo "   ❌ SYNTAX ERROR in trading_strategy.py"
    exit 1
fi
echo ""

# Start bot
echo "4. Starting bot with fixes..."
nohup python3 bot.py > nija_output.log 2>&1 &
BOT_PID=$!
echo "   Bot started with PID: $BOT_PID"
sleep 3
echo ""

# Verify it's running
echo "5. Verifying bot is running..."
if pgrep -f "python.*bot.py" > /dev/null; then
    echo "   ✅ Bot is running"
    ps aux | grep -E "python.*bot\.py" | grep -v grep
else
    echo "   ❌ Bot failed to start"
    echo "   Check logs: tail -50 nija_output.log"
    exit 1
fi
echo ""

# Show initial logs
echo "6. Checking initialization logs..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
tail -30 nija_output.log
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

echo "╔════════════════════════════════════════════════════════════════╗"
echo "║                    BOT RESTART COMPLETE                        ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""
echo "📊 NEXT STEPS:"
echo "   1. Monitor logs: tail -f nija_output.log"
echo "   2. Watch for CIRCUIT BREAKER message (balance < \$25)"
echo "   3. Deposit \$50-100 to Coinbase Advanced Trade"
echo "   4. Once deposited, bot will start trading with:"
echo "      • Min position: \$2.00"
echo "      • Max position: \$100.00"
echo "      • Circuit breaker: \$25 minimum balance"
echo ""
echo "🔍 To monitor in real-time:"
echo "   tail -f nija_output.log | grep -E 'Position size|TRADING HALTED|Executing|balance'"
echo ""
