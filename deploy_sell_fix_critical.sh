#!/bin/bash
# Deploy CRITICAL FIX: Bot buying but not selling

cd /workspaces/Nija

echo "="*80
echo "🚨 CRITICAL FIX DEPLOYMENT: BOT SELL ORDER LOGIC"
echo "="*80
echo ""

echo "📦 Staging changes..."
git add bot/trading_strategy.py
git add check_crypto_positions.py
git add emergency_liquidate.py
git add diagnose_sell_issue.py
git add take_profit_now.sh

echo ""
echo "✅ Committing..."
git commit -m "CRITICAL FIX: Bot now properly executes sell orders

PROBLEM:
- Bot was buying crypto successfully
- Bot NOT selling crypto - positions accumulating
- Exit conditions detected but orders not executing

ROOT CAUSE:
1. Sell order status checking 'error' instead of 'unfilled'
2. Missing logging for sell order execution
3. No visibility into why sells were failing

THE FIX:
bot/trading_strategy.py (lines 805-840):
- Check for BOTH 'unfilled' and 'error' status (was only checking 'error')
- Added detailed logging for sell order execution
- Log position size, crypto amount, current price before sell
- Log order status on each retry attempt
- Clearer error messages when sell fails

ADDITIONAL DIAGNOSTIC TOOLS:
- diagnose_sell_issue.py: Check why sells are failing
- check_crypto_positions.py: Verify current holdings
- emergency_liquidate.py: Manual liquidation without confirmation

IMPACT:
- Bot will now properly exit positions at stop-loss
- Bot will now properly exit positions at take-profit
- Trailing stops will actually close positions
- Profits can be realized instead of held indefinitely

TESTING NEEDED:
1. Deploy to Railway
2. Monitor next sell order execution
3. Verify positions actually close
4. Check logs for 'Order status = filled' messages

Related issue: #sell-orders-not-executing"

echo ""
echo "🚀 Pushing to GitHub..."
git push

echo ""
echo "="*80
echo "✅ DEPLOYMENT COMPLETE"
echo "="*80
echo ""
echo "📊 NEXT STEPS:"
echo "1. Run: bash commit_liquidation_scripts.sh (if not already done)"
echo "2. Check Railway deployment logs"
echo "3. Monitor for sell order execution"
echo "4. Run: python3 diagnose_sell_issue.py (to verify current state)"
echo ""
echo "💡 To manually liquidate existing positions:"
echo "   python3 emergency_liquidate.py"
echo ""
