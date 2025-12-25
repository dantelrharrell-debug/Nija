#!/bin/bash
cd /workspaces/Nija

git add -A

git commit -m "Add diagnostic and verification tools for Coinbase API connection

- Added DIAGNOSE_SELL_ISSUE.py: diagnose position tracking and sell logic
- Added VERIFY_API_CONNECTION.py: verify API credentials and account connection
- Added CHECK_ACCOUNT_STATUS.md: guide for checking account balances
- Added VERIFY_ACCOUNT_GUIDE.md: complete troubleshooting guide for API issues
- Added quick_commit_push.sh: commit and push helper script

These tools help diagnose why bot cannot see funds or positions:
- Position tracking verification
- API credential validation
- Consumer vs Advanced Trade balance detection
- Multi-account API key issues"

git push origin main

echo ""
echo "✅ Changes committed and pushed to GitHub"
