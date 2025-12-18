#!/bin/bash
echo "🔍 CHECKING IF BROKER_MANAGER.PY FIX IS ON GITHUB..."
echo ""

# Show recent commits
echo "Recent commits:"
git log --oneline -8
echo ""

# Check if broker_manager.py was modified recently
echo "Last modification to bot/broker_manager.py:"
git log --oneline -1 -- bot/broker_manager.py
echo ""

# Show what's in that commit
echo "What changed in broker_manager.py:"
git log -1 --stat -- bot/broker_manager.py
echo ""

# Verify the dual API code is in the committed version
echo "Checking if dual API code exists in committed version:"
if git show HEAD:bot/broker_manager.py | grep -q "Checking v2 API (Consumer wallets)"; then
    echo "✅ v2 API check FOUND in HEAD"
else
    echo "❌ v2 API check NOT FOUND in HEAD"
fi

if git show HEAD:bot/broker_manager.py | grep -q "Checking v3 API (Advanced Trade)"; then
    echo "✅ v3 API check FOUND in HEAD"
else
    echo "❌ v3 API check NOT FOUND in HEAD"
fi

if git show HEAD:bot/broker_manager.py | grep -q "TOTAL BALANCE (from v2 Consumer + v3 Advanced Trade APIs)"; then
    echo "✅ Dual API logging FOUND in HEAD"
else
    echo "❌ Dual API logging NOT FOUND in HEAD"
fi

echo ""
echo "Current branch and remote status:"
git status -sb
echo ""

# Check if we're ahead/behind remote
echo "Comparing with origin/main:"
git fetch origin main 2>&1 | grep -v "^From"
LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse origin/main)

if [ "$LOCAL" = "$REMOTE" ]; then
    echo "✅ Local and GitHub are IN SYNC"
    echo "   Both at commit: ${LOCAL:0:8}"
else
    echo "⚠️  Local and GitHub are OUT OF SYNC"
    echo "   Local:  ${LOCAL:0:8}"
    echo "   GitHub: ${REMOTE:0:8}"
fi
