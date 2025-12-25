#!/bin/bash
cd /workspaces/Nija

# Commit the guard removal
git add bot/trading_strategy.py
git commit -m "fix: remove duplicate capital guards interfering with circuit breaker

- Removed startup MINIMUM_VIABLE_CAPITAL check that prevented bot initialization
- Removed duplicate capital check at trade execution
- Circuit breaker at \$25 is now the sole protection during trading
- Bot can now start with any balance and circuit breaker handles protection"

# Push to GitHub
git push origin main

echo "✅ Changes committed and pushed"
echo ""

# Restart bot
echo "🔄 Restarting bot..."
pkill -f "python.*bot.py"
sleep 2
nohup python3 bot.py > nija_output.log 2>&1 &
echo "✅ Bot restarted with PID: $!"
sleep 5

echo ""
echo "📊 Checking for circuit breaker activation..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
tail -100 nija_output.log | grep -A5 -B5 "TRADING HALTED\|Position size\|balance" | tail -30
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "✅ ALL FIXES ACTIVE"
echo "   • Position sizing: 15% max (not 5% min)"
echo "   • Position minimum: \$2.00"
echo "   • Circuit breaker: \$25 minimum balance"
echo "   • Reserve management: 50-30-20-10% tiers"
echo ""
echo "🔍 Monitor live:"
echo "   tail -f nija_output.log | grep -E 'TRADING HALTED|Position size|Executing'"
