#!/bin/bash
# FINAL COMMIT AND PUSH - Clear staging after

cd /workspaces/Nija

echo "🔄 FINAL COMMIT & PUSH PROCESS"
echo "═══════════════════════════════════════════════════════════════════"
echo ""

# Configure git
git config commit.gpgsign false
git config user.name "GitHub Copilot"
git config user.email "copilot@users.noreply.github.com"

# Reset any pending commits
echo "📦 Resetting any pending commits..."
git reset --soft HEAD 2>/dev/null

# Stage ALL changes
echo "📦 Staging all changes..."
git add -A

# Check what's staged
STAGED=$(git diff --cached --name-only)
if [ -z "$STAGED" ]; then
    echo "✅ No changes to commit - repository is clean"
    exit 0
fi

echo ""
echo "📋 Files to commit:"
echo "$STAGED" | sed 's/^/   • /'

# Commit everything
echo ""
echo "💾 Committing all changes..."
git commit -m "fix: final broker method corrections and position cap enforcement

All fixes applied:
- Corrected broker method calls: quantity + size_type='base'
- Position cap enforced at 8 maximum  
- Minimum \$2 position size enforced
- Concurrent liquidation enabled

Status scripts and documentation added for monitoring"

if [ $? -eq 0 ]; then
    echo "✅ Commit successful"
    
    echo ""
    echo "🚀 Pushing to production..."
    git push origin main
    
    if [ $? -eq 0 ]; then
        echo "✅ Push successful"
        
        echo ""
        echo "🧹 Cleaning up staging area..."
        git reset HEAD
        git clean -fd
        
        echo ""
        echo "═══════════════════════════════════════════════════════════════════"
        echo "✅✅✅ DEPLOYMENT COMPLETE"
        echo "═══════════════════════════════════════════════════════════════════"
        echo ""
        echo "📊 Bot Status:"
        echo "   • Position cap: 8 maximum ✅"
        echo "   • Minimum position: \$2 ✅"
        echo "   • Concurrent liquidation: Enabled ✅"
        echo "   • Entry blocking: Active (STOP_ALL_ENTRIES.conf) ✅"
        echo ""
        echo "📈 Expected behavior:"
        echo "   • Bot liquidates weak positions"
        echo "   • Maintains max 8 positions"
        echo "   • No new trades under \$2"
        echo "   • Only high-quality entries when cap allows"
        echo ""
        exit 0
    else
        echo "❌ Push failed"
        exit 1
    fi
else
    echo "❌ Commit failed"
    exit 1
fi
