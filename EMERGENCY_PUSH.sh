#!/bin/bash
echo "🚨 EMERGENCY: PUSHING BROKER FIX TO GITHUB NOW!"
echo ""
echo "Render is still showing \$25.81 instead of \$30.64"
echo "This means the broker_manager.py fix hasn't been deployed yet."
echo ""

# Add the critical file
git add bot/broker_manager.py

# Also add diagnostic files
git add check_my_account.py diagnose_account_types.py TRANSFER_FUNDS_NOW.md deploy_render_fix.sh PUSH_CRITICAL_FIX.sh 2>/dev/null || true

# Show what we're committing
echo "Files to commit:"
git status --short

echo ""
echo "Committing..."

git commit -m "🚨 EMERGENCY FIX: Detect full \$30.64 in Advanced Trade

CURRENT PROBLEM (from Render logs):
- Balance detected: \$25.81 (WRONG)
- Should detect: \$30.64 (user's actual Advanced Trade balance)
- Trades failing: INSUFFICIENT_FUND errors

ROOT CAUSE:
- Render still running OLD code (only v3 API, incomplete)
- Missing v2 API check for full balance picture

THIS FIX:
Modified bot/broker_manager.py lines 150-280 to:
1. Check v2 Consumer API via JWT authentication
2. Check v3 Advanced Trade API
3. Sum balances from BOTH sources
4. Enhanced logging to show where balances come from

EXPECTED RESULT:
- Logs will show: 'TRADING BALANCE: \$30.XX'
- Trades will execute successfully
- No more INSUFFICIENT_FUND errors

Files modified:
- bot/broker_manager.py: Core balance detection fix

Test indicators after deployment:
✅ Look for: '💰 Checking v2 API (Consumer wallets)...'
✅ Look for: '💰 Checking v3 API (Advanced Trade)...'
✅ Look for: '💰 TOTAL BALANCE: \$30.XX'
✅ Trades should succeed with no INSUFFICIENT_FUND errors"

echo ""
echo "Pushing to GitHub..."
git push origin main

echo ""
echo "=========================================="
echo "✅ PUSHED TO GITHUB!"
echo "=========================================="
echo ""
echo "Render will auto-deploy in ~2-3 minutes"
echo ""
echo "What to watch for in logs:"
echo "  1. '💰 Checking v2 API (Consumer wallets)...'"
echo "  2. '💰 Checking v3 API (Advanced Trade)...'"
echo "  3. 'TRADING BALANCE: \$30.XX' (not \$25.81)"
echo "  4. '📤 Placing BUY order...' → SUCCESS (no INSUFFICIENT_FUND)"
echo ""
echo "Monitor at: https://dashboard.render.com"
echo ""
