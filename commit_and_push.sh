#!/bin/bash
cd /workspaces/Nija

echo "� Staging all changes..."
git add -A

echo "📝 Creating commit..."
git -c commit.gpgsign=false commit -m "Add balance diagnostic tools

- Add diagnose_balance.py: comprehensive account diagnostic script
- Add test_raw_api.py: raw API testing with JWT authentication
- These scripts help diagnose \$0 balance detection issues
- Both scripts test Coinbase Advanced Trade API connectivity
- Show exact API responses and troubleshooting guidance"

if [ $? -eq 0 ]; then
    echo "✅ Commit created successfully"
else
    echo "⚠️ Nothing new to commit or commit failed"
fi

echo "🚀 Pushing to origin main..."
git push origin main

if [ $? -eq 0 ]; then
    echo ""
    echo "✅ ============================================"
    echo "✅  SUCCESSFULLY PUSHED TO GITHUB!"
    echo "✅ ============================================"
else
    echo "❌ Push failed - check git status"
    git status
fi

