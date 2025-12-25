#!/bin/bash
# Deploy critical balance fix to production

echo "========================================="
echo "DEPLOYING CRITICAL BALANCE FIX"
echo "========================================="
echo ""
echo "Changes:"
echo "- Fixed balance calculation to only use Advanced Trade portfolio"
echo "- Consumer wallet balance tracked separately (not included in tradable balance)"
echo "- Enhanced logging and error messages"
echo ""

# Add all changes
git add -A

# Commit
git commit -m "CRITICAL FIX: Separate Consumer vs Advanced Trade balance

Problem: Bot showed \$25.81 available but all trades failed with INSUFFICIENT_FUND
Root cause: Balance check was adding Consumer wallet + Advanced Trade, but only Advanced Trade is tradable

Changes:
- Modified get_account_balance() to ONLY return Advanced Trade balance
- Consumer balance now tracked separately for diagnostics only  
- Enhanced logging to clearly mark which balances are tradable
- Better error messages when funds are in wrong place
- Added check_balance_location.py diagnostic script

This prevents balance mismatches and makes it clear when funds need to be transferred to Advanced Trade portfolio."

# Push to GitHub
echo ""
echo "Pushing to GitHub..."
git push origin main

echo ""
echo "========================================="
echo "✅ DEPLOYMENT COMPLETE"
echo "========================================="
echo ""
echo "Next steps:"
echo "1. Run: python check_balance_location.py"
echo "2. Transfer funds to Advanced Trade if needed"
echo "3. Bot will automatically use correct balance"
echo ""
