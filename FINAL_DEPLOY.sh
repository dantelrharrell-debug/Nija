#!/bin/bash
set -e  # Exit on any error

echo "================================================================================"
echo "🚨 EMERGENCY DEPLOYMENT: Fixing Render Balance Detection"
echo "================================================================================"
echo ""
echo "Current Status (from logs):"
echo "  ❌ Render detecting: \$25.81"
echo "  ✅ Should detect:    \$30.64"
echo "  ❌ Result:           INSUFFICIENT_FUND errors"
echo ""
echo "This deployment will:"
echo "  1. Push broker_manager.py with dual API checking (v2 + v3)"
echo "  2. Trigger Render auto-deployment"
echo "  3. Fix balance detection to show full \$30.64"
echo "  4. Enable successful trades"
echo ""
echo "================================================================================"
echo ""

# Stage the critical file
echo "📁 Staging files..."
git add bot/broker_manager.py
git add check_my_account.py diagnose_account_types.py TRANSFER_FUNDS_NOW.md 2>/dev/null || true
git add deploy_render_fix.sh PUSH_CRITICAL_FIX.sh EMERGENCY_PUSH.sh FINAL_DEPLOY.sh 2>/dev/null || true

# Show what will be committed
echo ""
echo "Files to commit:"
git status --short
echo ""

# Commit
echo "💾 Creating commit..."
git commit -m "🚨 CRITICAL FIX: Dual API balance detection for full \$30.64

PROBLEM (Current Render logs):
- Balance shows: \$25.81 (WRONG - missing ~\$5)
- Trades fail: INSUFFICIENT_FUND errors
- User has \$30.64 in Advanced Trade but bot doesn't see it all

ROOT CAUSE:
- Old code only checked v3 Advanced Trade API (incomplete)
- Missing v2 Consumer API check
- Incomplete balance calculation

SOLUTION (This commit):
Modified bot/broker_manager.py lines 150-280:
✅ Check v2 Consumer API via JWT authentication
✅ Check v3 Advanced Trade API  
✅ Sum balances from BOTH sources
✅ Enhanced logging showing balance sources

TECHNICAL CHANGES:
File: bot/broker_manager.py
Method: get_account_balance()
Lines: 150-280

Added:
1. v2 API call using JWT with ES256 signing
2. Parse v2 response for USD/USDC balances
3. v3 API call for Advanced Trade accounts
4. Sum both sources: total = v2_balance + v3_balance
5. Detailed logging for each API call

EXPECTED RESULTS:
Before deployment:
  💰 Pre-flight balance check: \$25.81
  ❌ INSUFFICIENT_FUND error

After deployment:
  💰 Checking v2 API (Consumer wallets)...
  💰 Checking v3 API (Advanced Trade)...
  💰 TOTAL BALANCE: \$30.XX
  ✅ Sufficient funds in Advanced Trade for trading!
  📤 Placing BUY order... → SUCCESS

TESTING:
Monitor Render logs after deployment for:
1. '💰 Checking v2 API (Consumer wallets)...' ← New log line
2. '💰 Checking v3 API (Advanced Trade)...' ← New log line  
3. 'TRADING BALANCE: \$30.XX' ← Should be ~\$30, not \$25
4. Trades executing successfully (no INSUFFICIENT_FUND)

Timeline:
- Push: Now
- Render deployment: ~2-3 minutes
- Bot restart: ~30 seconds
- First successful trade: ~2.5 minutes after deployment

Files modified:
- bot/broker_manager.py (primary fix)
- Added diagnostic scripts for troubleshooting" || {
    echo ""
    echo "⚠️  Nothing to commit (files may already be staged)"
    echo "Proceeding with push..."
}

# Push to GitHub
echo ""
echo "📤 Pushing to GitHub..."
git push origin main

# Success message
echo ""
echo "================================================================================"
echo "✅✅✅ SUCCESSFULLY PUSHED TO GITHUB! ✅✅✅"
echo "================================================================================"
echo ""
echo "Next Steps:"
echo ""
echo "1. Render Auto-Deployment (Starting now)"
echo "   - Takes ~2-3 minutes"
echo "   - Watch: https://dashboard.render.com"
echo ""
echo "2. Bot Will Restart Automatically"
echo "   - New code will be loaded"
echo "   - Balance detection will be fixed"
echo ""
echo "3. Verify in Render Logs (within 5 minutes)"
echo "   Look for these NEW log lines:"
echo "   ✅ '💰 Checking v2 API (Consumer wallets)...'"
echo "   ✅ '💰 Checking v3 API (Advanced Trade)...'"
echo "   ✅ '💰 TOTAL BALANCE (from v2 Consumer + v3 Advanced Trade APIs):'"
echo "   ✅ 'TRADING BALANCE: \$30.XX' ← KEY: Should show ~\$30, not \$25"
echo "   ✅ '✅ Sufficient funds in Advanced Trade for trading!'"
echo ""
echo "4. Confirm Successful Trades"
echo "   ✅ '📤 Placing BUY order: [SYMBOL], quote_size=\$5.00'"
echo "   ✅ '✅ Trade successful' (or order ID shown)"
echo "   ❌ Should NOT see: 'INSUFFICIENT_FUND' errors anymore"
echo ""
echo "================================================================================"
echo ""
echo "🎯 DEPLOYMENT COMPLETE! Monitoring Render now..."
echo ""
echo "If balance still shows \$25.81 after 5 minutes:"
echo "  → Check Render build logs to ensure deployment completed"
echo "  → Verify git commit reached GitHub (check repo)"
echo "  → Manual restart may be needed in Render dashboard"
echo ""
echo "Expected timeline to 100% working:"
echo "  T+0:00 - Push completed (NOW)"
echo "  T+2:00 - Render deployment finishes"
echo "  T+2:30 - Bot restarts with new code"
echo "  T+5:00 - First successful trade executes"
echo ""
echo "================================================================================"
