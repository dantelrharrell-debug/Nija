#!/bin/bash
# Deploy critical balance detection fix to Render

echo "🚀 DEPLOYING CRITICAL BALANCE FIX TO RENDER"
echo "="*60
echo ""
echo "PROBLEM: Bot was only checking v3 Advanced Trade API"
echo "         Missing Consumer wallet balances ($$$)"
echo ""
echo "FIX:     Now checks BOTH v2 Consumer + v3 Advanced Trade APIs"
echo "         Will detect your funds wherever they are!"
echo ""
echo "="*60
echo ""

# Stage all changes
git add bot/broker_manager.py
git add TRANSFER_FUNDS_NOW.md
git add check_my_account.py
git add deploy_render_fix.sh
git add diagnose_account_types.py
git add push_balance_fix.sh

# Commit
git commit -m "CRITICAL FIX: Check BOTH v2 Consumer + v3 Advanced Trade APIs for balance

Previous code only checked v3 Advanced Trade API, missing Consumer wallet balances.
User has funds but bot was reporting \$0.00 because funds are in Consumer wallet.

Changes to bot/broker_manager.py:
- Added v2 API check using JWT to detect Consumer wallet balances  
- Keep v3 API check for Advanced Trade balances
- Sum balances from BOTH APIs for accurate total
- Updated logging to show balance source and account type

Also added diagnostic tools:
- check_my_account.py: Quick balance checker
- diagnose_account_types.py: Deep account diagnostics
- TRANSFER_FUNDS_NOW.md: User guide for fund transfers

This should immediately show correct balance on next Render deployment."

echo ""
echo "✅ Changes committed!"
echo ""
echo "📤 Pushing to GitHub..."
git push origin main

echo ""
echo "="*60  
echo "🎯 PUSHED TO GITHUB!"
echo "="*60
echo ""
echo "Render will auto-deploy in ~2 minutes"
echo ""
echo "Watch deployment: https://dashboard.render.com"
echo ""
echo "After deployment, check logs for:"
echo "  💰 Checking v2 API (Consumer wallets)..."
echo "  ✅ USD: \$XX.XX (type=wallet, name=...)"
echo "  💰 TOTAL BALANCE: \$XX.XX"
echo ""
echo "Bot should detect your balance and start trading!"
echo "="*60
