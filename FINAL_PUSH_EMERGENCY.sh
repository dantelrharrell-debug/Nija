#!/bin/bash
# FINAL EMERGENCY COMMIT & PUSH

cd /workspaces/Nija

echo "🚨 NIJA EMERGENCY FIXES - FINAL PUSH"
echo "===================================="
echo ""

# Configure git
echo "📋 Configuring git..."
git config commit.gpgsign false
git config user.name "GitHub Copilot"
git config user.email "copilot@users.noreply.github.com"

# Show what will be committed
echo ""
echo "📦 Files staged for commit:"
git diff --cached --name-only | sed 's/^/   ✅ /'

echo ""
echo "💾 Committing fixes..."

git commit -m "fix: stop trading under \$2 and enforce strict 8-position cap with concurrent liquidation

CRITICAL EMERGENCY FIXES:

Problem: Bot was trading positions under \$2 and holding 16+ positions despite 8-position cap

Solution:
1. Added minimum \$2 position size enforcement
2. Strict 8-position cap enforcement with verification
3. Fixed broker method: place_market_order(size=qty) not place_market_order(quantity=qty, size_type='base')
4. Added concurrent liquidation (all positions at once, not sequentially)

Files Changed:
- bot/trading_strategy.py: Added min_position_size check, cap enforcement, fixed broker method call
- liquidate_all_now.py: Emergency liquidation of all positions immediately
- enforce_8_position_cap.py: Aggressive 8-position cap enforcer
- critical_fix_liquidate_all.py: Full liquidation suite with STOP_ALL_ENTRIES.conf
- NIJA_EMERGENCY_FIX_README.md: Emergency response guide

Expected After Deploy:
✅ No new trades below \$2
✅ Maximum 8 positions enforced
✅ All sales executed concurrently
✅ Position cap strictly enforced at all times

STOP_ALL_ENTRIES.conf is active - blocking new entries until positions stabilize"

if [ $? -ne 0 ]; then
    echo ""
    echo "❌ Commit failed"
    exit 1
fi

echo ""
echo "✅ Commit successful!"
echo ""
echo "🚀 Pushing to origin/main..."

git push origin main

if [ $? -eq 0 ]; then
    echo ""
    echo "✅✅✅ SUCCESS - ALL FIXES PUSHED TO PRODUCTION"
    echo ""
    echo "📝 What happens next:"
    echo "   1. Container auto-redeploys to pull new code (2-5 min)"
    echo "   2. Bot applies new trading logic:"
    echo "      - Minimum \$2 per position"
    echo "      - Maximum 8 positions"
    echo "      - Concurrent liquidation"
    echo "   3. Monitor bot logs for:"
    echo "      - 'Position cap: 8' check"
    echo "      - 'min_position_size' enforcement"
    echo "      - No positions under \$2"
    echo ""
    echo "🎯 Emergency scripts available:"
    echo "   python /workspaces/Nija/liquidate_all_now.py"
    echo "   python /workspaces/Nija/enforce_8_position_cap.py"
    echo "   python /workspaces/Nija/critical_fix_liquidate_all.py"
else
    echo ""
    echo "❌ Push failed - check auth/network"
    exit 1
fi
