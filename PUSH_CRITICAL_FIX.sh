#!/bin/bash
echo "🚨 PUSHING CRITICAL FIX TO GITHUB..."
echo ""
echo "Changes to push:"
echo "  bot/broker_manager.py - Dual API balance detection (v2 + v3)"
echo ""

cd /workspaces/Nija

# Stage ALL changes including broker_manager.py
git add bot/broker_manager.py
git add *.py *.sh *.md 2>/dev/null
git status --short

echo ""
echo "📝 Committing..."

git commit -m "CRITICAL: Detect full Advanced Trade balance via dual API check

Fixed INSUFFICIENT_FUND errors on Render by implementing proper balance detection:

BEFORE:
- Only checked v3 Advanced Trade API
- Only detected \$25.81 (missed ~\$5)
- Railway worked but Render failed

AFTER:
- Check v2 Consumer API via JWT
- Check v3 Advanced Trade API
- Sum both sources for accurate total
- Should now detect full \$30.64

This fix ensures Render detects the same balance as Railway (~\$30.64)
and stops INSUFFICIENT_FUND errors during order placement.

Modified:
- bot/broker_manager.py lines 150-280: Added dual API checking

Test after deployment:
- Look for log: '💰 TOTAL BALANCE (from v2 Consumer + v3 Advanced Trade APIs):'
- Should show: 'TRADING BALANCE: \$30.XX'
- Orders should now execute successfully"

echo ""
echo "📤 Pushing to GitHub..."
git push origin main

echo ""
echo "✅ COMPLETE!"
echo ""
echo "Render auto-deployment triggered"
echo "Check https://dashboard.render.com for deployment status"
echo ""
echo "Expected in logs after ~2 minutes:"
echo "  💰 TOTAL BALANCE: \$30.XX"
echo "  ✅ Sufficient funds in Advanced Trade for trading!"
