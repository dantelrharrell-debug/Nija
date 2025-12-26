#!/bin/bash
# Commit and push position cap enforcer fix

cd /workspaces/Nija

echo "🔧 Committing position cap enforcer fix..."

git config commit.gpgsign false
git config user.email "copilot@users.noreply.github.com"
git config user.name "GitHub Copilot"

git add bot/position_cap_enforcer.py

git commit -m "fix: correct broker method signature in position cap enforcer

Replace 'size' parameter with 'quantity' and 'size_type=base' to match
the corrected broker API signature.

This fixes the runtime error:
  BaseBroker.place_market_order() got an unexpected keyword argument 'size'

Now position cap enforcer can successfully liquidate excess positions
when over the 8-position limit.

Changes:
- bot/position_cap_enforcer.py: Use quantity + size_type='base' instead of size"

if [ $? -eq 0 ]; then
    echo "✅ Commit successful"
    
    echo ""
    echo "🚀 Pushing to copilot/start-apex-trading-bot branch..."
    git push origin copilot/start-apex-trading-bot
    
    if [ $? -eq 0 ]; then
        echo "✅ Push successful!"
        echo ""
        echo "📦 Deployment will auto-update in ~30 seconds"
    else
        echo "❌ Push failed"
        exit 1
    fi
else
    echo "❌ Commit failed"
    exit 1
fi
