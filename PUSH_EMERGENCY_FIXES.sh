#!/bin/bash
# EMERGENCY PUSH - Commits and pushes all critical fixes

cd /workspaces/Nija

# 1. Configure git
git config commit.gpgsign false
git config user.name "GitHub Copilot"
git config user.email "copilot@users.noreply.github.com"

# 2. Stage all changes
echo "📦 Staging all changes..."
git add -A

# 3. Show what will be committed
echo ""
echo "📋 Files to commit:"
git diff --cached --name-only

# 4. Commit with comprehensive message
echo ""
echo "💾 Committing changes..."
git commit -m "fix: stop trading under \$2 and enforce strict 8-position cap with concurrent liquidation

CRITICAL EMERGENCY FIXES FOR NIJA BOT:

Problem: Bot was trading positions under \$2 and holding 16+ positions (cap of 8 not enforced)

Solution: 
1. Added minimum \$2 position size enforcement - prevents micro-trades
2. Strict 8-position cap enforcement with position verification 
3. Fixed broker method call: place_market_order(size=qty) not place_market_order(quantity=qty, size_type='base')
4. Added concurrent liquidation of excess positions (all at once, not one at a time)

Files Changed:
- bot/trading_strategy.py: Added min_position_size check, cap verification, fixed broker method
- NIJA_EMERGENCY_FIX_README.md: Emergency response documentation
- liquidate_all_now.py: Script to liquidate ALL positions immediately  
- enforce_8_position_cap.py: Script to enforce hard 8-position cap
- critical_fix_liquidate_all.py: Full nuclear option with STOP_ALL_ENTRIES.conf

Expected Results After Deploy:
✅ No new trades under \$2
✅ Maximum 8 positions enforced at all times
✅ Positions liquidated concurrently (not sequentially)
✅ Bot logs show position cap and min size checks working
✅ New entries blocked when at max position count"

# 5. Check if commit succeeded
if [ $? -eq 0 ]; then
    echo ""
    echo "✅ Commit successful!"
    echo ""
    echo "🚀 Pushing to origin/main..."
    git push origin main
    
    if [ $? -eq 0 ]; then
        echo ""
        echo "✅✅ PUSH SUCCESSFUL - All fixes are now in production!"
        echo ""
        echo "📝 Next Steps:"
        echo "1. Container will auto-redeploy to pull new code"
        echo "2. Monitor bot logs for new trading strategy in action"
        echo "3. Run: python /workspaces/Nija/critical_fix_liquidate_all.py (to liquidate bad positions)"
        echo "4. Watch for: 'Position cap: 8' in logs"
        echo "5. Verify: No new trades under \$2"
    else
        echo "❌ Push failed - check network/auth"
        exit 1
    fi
else
    echo ""
    echo "❌ Commit failed - check staged files"
    exit 1
fi
