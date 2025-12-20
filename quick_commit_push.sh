#!/bin/bash
cd /workspaces/Nija

echo "📦 Staging all changes..."
git add -A

echo "📝 Committing changes..."
git -c commit.gpgsign=false commit -m "Add comprehensive portfolio analysis and monitoring tools

- Added deep portfolio scanning (DEEP_PORTFOLIO_SCAN.py, DEEP_ORDER_ANALYSIS.py)
- Added position checking scripts (CHECK_POSITIONS_NOW.py, COMPARE_POSITIONS.py)
- Added force-close and sell tools (FORCE_CLOSE_ALL.py, FORCE_SELL_ALL_POSITIONS.py)
- Added Railway deployment verification (check_railway_status.sh, verify_railway_stopped.sh)
- Added bot activity monitoring (check_real_activity.py, check_if_bot_stopped.py)
- Added cash location and portfolio analysis (CHECK_CASH_LOCATION.py, CHECK_ALL_PORTFOLIOS.py)
- Added auto-buy stop documentation (STOP_AUTO_BUY.md)"

if [ $? -eq 0 ]; then
    echo "✅ Commit created successfully"
    echo ""
    echo "🚀 Pushing to origin main..."
    git push origin main
    
    if [ $? -eq 0 ]; then
        echo ""
        echo "✅ ============================================"
        echo "✅  SUCCESSFULLY PUSHED TO GITHUB!"
        echo "✅ ============================================"
    else
        echo ""
        echo "❌ Push failed. Check your connection or credentials."
    fi
else
    echo "⚠️ Nothing new to commit or commit failed"
fi
