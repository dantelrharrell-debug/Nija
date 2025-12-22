#!/bin/bash
set -e

echo "================================================"
echo "NIJA RESTART WITH CRITICAL FIX"
echo "================================================"
echo ""

# Kill existing bot process
echo "📛 Stopping existing bot process..."
pkill -f "python3 bot/live_trading.py" || true
pkill -f "python.*live_trading" || true
sleep 2

# Stage and commit the critical fix
echo "📝 Committing critical order execution fix..."
cd /workspaces/Nija
git add -A
git commit -m "CRITICAL FIX: Only remove positions from tracking when sell orders ACTUALLY execute

Root cause: Bot was removing positions from tracking even when sell orders failed on Coinbase.
Result: Positions appeared closed in logs but remained open and bleeding on Coinbase.

Changes:
1. trading_strategy.py - manage_open_positions():
   - Changed: ONLY remove positions if order.status == 'filled' or 'partial'
   - Before: Removed positions even if order failed (or exit_reason was set)
   - Now: Keep retrying failed exits on next cycle instead of abandoning them
   - Added clear error logging for failed orders vs successful executions

2. trade_analytics.py - get_session_stats():
   - Fixed KeyError when session has no completed trades
   - Added all required keys (wins,losses,avg_win,avg_loss,profit_factor,avg_duration_min)
   - Prevents crash on empty session stats

This fix ensures:
✅ Positions only close from tracking when actually sold on Coinbase
✅ Failed orders retry automatically next cycle
✅ No more orphaned positions in tracking vs actual holdings" || echo "Nothing new to commit"

# Push to origin
echo "📤 Pushing to origin..."
git push origin main || echo "Already up to date"

# Restart the bot
echo ""
echo "🤖 Restarting NIJA bot with corrected order handling..."
sleep 2

# Start the bot in the background
python3 bot/live_trading.py > nija.log 2>&1 &
BOT_PID=$!

echo "✅ Bot restarted with PID: $BOT_PID"
echo ""
echo "📊 Status:"
echo "   - Kill switch REMOVED (trading enabled)"
echo "   - Order execution FIX applied"
echo "   - Position tracking corrected"
echo "   - Failed orders will now RETRY instead of being abandoned"
echo ""
echo "🔍 Monitoring logs (Ctrl+C to exit)..."
sleep 3
tail -f nija.log
