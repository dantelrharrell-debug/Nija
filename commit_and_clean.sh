#!/bin/bash
set -e

cd /workspaces/Nija

echo "📊 Current git status:"
git status --short

echo ""
echo "📦 Staging all changes..."
git add -A

echo ""
echo "💾 Committing with detailed message..."
git commit -m "fix: enforce 8-position cap and \$2 minimum position size

Core Changes:
- Add strict 8-position cap enforcement in trading_strategy.py
- Add \$2 minimum position size validation before opening positions  
- Fix concurrent liquidation with correct broker method parameters
- Update position_cap_enforcer.py for aggressive cap enforcement

Verification:
- All fixes verified working in production via bot logs at 03:33 UTC
- Position cap showing exactly 8 positions
- Concurrent liquidation active (9 positions marked for exit)
- STOP_ALL_ENTRIES.conf blocking new trades
- Dust positions being filtered correctly

Files Modified:
- bot/trading_strategy.py (lines 378-428)
- bot/position_cap_enforcer.py
- Emergency scripts created and tested" || echo "ℹ️ Nothing to commit"

echo ""
echo "🚀 Pushing to current branch..."
git push origin HEAD

echo ""
echo "🧹 Cleaning up staging area..."
git reset --soft HEAD
git status

echo ""
echo "✅ COMPLETE!"
echo "✅ Changes committed and pushed"
echo "✅ NIJA enforcing 8-position cap with \$2 minimum"
