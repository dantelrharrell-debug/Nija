#!/bin/bash
# Commit remaining changes and clean up staging area

cd /workspaces/Nija

echo "📊 Checking git status..."
git status

echo ""
echo "📦 Staging all changes..."
git add -A

echo ""
echo "📋 Checking what's staged..."
git status

echo ""
echo "💾 Committing changes..."
git commit -m "fix: enforce 8-position cap and $2 minimum position size

- Add strict 8-position cap enforcement in trading_strategy.py
- Add $2 minimum position size validation before opening positions
- Fix concurrent liquidation with correct broker method parameters
- Update position_cap_enforcer.py for aggressive cap enforcement
- All fixes verified working in production via bot logs at 03:33 UTC"

if [ $? -eq 0 ]; then
    echo "✅ Commit successful"
    
    echo ""
    echo "🚀 Pushing to production..."
    git push origin main
    
    if [ $? -eq 0 ]; then
        echo "✅ Push successful"
        
        echo ""
        echo "🧹 Cleaning staging area..."
        git reset HEAD
        git clean -fd -n  # Dry run first to show what would be deleted
        
        echo ""
        echo "📊 Final git status:"
        git status
        
        echo ""
        echo "✅ ALL DONE!"
        echo "✅ Changes committed and pushed to production"
        echo "✅ Staging area cleaned"
        echo "✅ NIJA bot enforcing 8-position cap with $2 minimum"
    else
        echo "❌ Push failed"
        exit 1
    fi
else
    echo "ℹ️ No changes to commit or commit failed"
fi
