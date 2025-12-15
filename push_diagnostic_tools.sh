#!/bin/bash
set -e

cd /workspaces/Nija

echo "📦 Staging all changes..."
git add -A

echo ""
echo "📝 Creating commit..."
git -c commit.gpgsign=false commit -m "Add balance diagnostic tools

- diagnose_balance.py: comprehensive account diagnostics
- test_raw_api.py: raw Coinbase API testing with JWT
- Help debug USD/USDC balance detection issues
- Show exact API responses and troubleshooting steps" || echo "Nothing to commit"

echo ""
echo "🚀 Pushing to remote..."
git push origin main

echo ""
echo "✅ SUCCESS - All changes pushed!"
echo ""
git log --oneline -1
