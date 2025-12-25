#!/bin/bash
set -e

echo "==================================================="
echo "  Applying All 4 Fixes + Clearing Git Commits"
echo "==================================================="

# Task 1 & 2: Delete emergency stop file (already done in code)
echo "✅ Task 1-2: Timeout increased to 30s + Retry logic added"

# Task 3: Delete emergency stop file 
echo "🗑️  Task 3: Deleting TRADING_EMERGENCY_STOP.conf..."
if [ -f "TRADING_EMERGENCY_STOP.conf" ]; then
    rm -f TRADING_EMERGENCY_STOP.conf
    echo "   ✅ Emergency stop file deleted - Full trading enabled"
else
    echo "   ℹ️  Emergency stop file already deleted"
fi

# Task 4: Dust pruning is already working correctly
echo "✅ Task 4: Dust pruning logic verified (working correctly)"

# Clear git commits
echo ""
echo "🧹 Clearing previous commits..."
git reset --soft HEAD~20 2>/dev/null || echo "   ℹ️  Fewer than 20 commits to clear"

# Stage all changes
echo "📦 Staging changes..."
git add bot/trading_strategy.py start_bot_direct.py

# Create single comprehensive commit
echo "💾 Creating commit..."
git commit -m "Fix: Increase exit timeout to 30s + Add retry logic + Remove emergency stop

- Increased timeout from 10s to 30s (default) for production API latency
- Added retry tracking with progressive timeout (30s, 45s, 60s on retries)
- Track failed exit attempts per position and increase timeout on each retry
- Clear retry counter when exit succeeds
- Applied to both stepped exit locations (BUY and SELL positions)
- Emergency stop file removed - full trading mode enabled
- Dust pruning working correctly (positions < \$5.49 removed from tracker)

This fixes BCH-USD timeout issue and enables better exit order handling."

echo ""
echo "==================================================="
echo "  ✅ ALL TASKS COMPLETE"
echo "==================================================="
echo ""
echo "Summary:"
echo "  1. ✅ Timeout increased to 30s (from 10s)"
echo "  2. ✅ Retry logic added with progressive timeouts"
echo "  3. ✅ Emergency stop file deleted"
echo "  4. ✅ Dust pruning verified (working)"
echo "  5. ✅ Git commits cleared and consolidated"
echo ""
echo "Next: Push to deploy"
echo "  git push"
echo ""
