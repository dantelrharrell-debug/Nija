#!/bin/bash
set -e

echo "=========================================="
echo "CRITICAL FIX EXECUTION SEQUENCE"
echo "=========================================="

# Step 1: Kill the current bot process
echo ""
echo "[Step 1] Killing current bot process..."
pkill -f "python3 bot/live_trading.py" ; sleep 2 || true
echo "✓ Process killed"

# Step 2: Stage all changes
echo ""
echo "[Step 2] Staging all changes..."
git add -A
echo "✓ Changes staged"

# Step 3: Commit with message
echo ""
echo "[Step 3] Committing changes..."
git commit -m "CRITICAL FIX: Only remove positions from tracking when sell orders ACTUALLY execute

Root cause: Bot was removing positions from tracking even when sell orders failed on Coinbase.
Result: Positions appeared closed in logs but remained open and bleeding on Coinbase.

Changes:
1. trading_strategy.py - manage_open_positions():
   - Changed: ONLY remove positions if order.status == 'filled' or 'partial'
   - Before: Removed positions even if order failed
   - Now: Keep retrying failed exits on next cycle
   - Added error logging for failed orders

2. trade_analytics.py - get_session_stats():
   - Fixed KeyError when session has no completed trades
   - Added all required keys

Result: Failed orders now retry instead of being abandoned"
echo "✓ Commit completed"

# Step 4: Push to origin
echo ""
echo "[Step 4] Pushing to origin..."
git push origin main
echo "✓ Push completed"

# Step 5: Start the bot
echo ""
echo "[Step 5] Starting bot..."
cd /workspaces/Nija && python3 bot/live_trading.py &
BOT_PID=$!
echo "✓ Bot started with PID: $BOT_PID"

# Step 6: Wait and show logs
echo ""
echo "[Step 6] Waiting 3 seconds and showing logs..."
sleep 3
echo ""
echo "=========================================="
echo "LAST 20 LINES OF nija.log:"
echo "=========================================="
tail -20 nija.log 2>/dev/null || echo "Log file not yet available"
echo ""
echo "=========================================="
echo "EXECUTION COMPLETE"
echo "=========================================="
echo "Bot Process ID: $BOT_PID"
ps aux | grep "python3 bot/live_trading.py" | grep -v grep || echo "Bot process verification pending"
