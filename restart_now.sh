#!/bin/bash
echo "🔄 Restarting NIJA bot with all fixes..."
cd /workspaces/Nija
pkill -f "python.*bot.py"
sleep 2
nohup python3 bot.py > nija_output.log 2>&1 &
echo "✅ Bot restarted! PID: $!"
sleep 5
echo ""
echo "📊 Initial logs:"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
tail -50 nija_output.log
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "🔍 Monitor circuit breaker:"
echo "   tail -f nija_output.log | grep -E 'TRADING HALTED|Position size'"
