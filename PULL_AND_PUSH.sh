#!/bin/bash
# Pull and push with force if needed

cd /workspaces/Nija

git pull --rebase origin main

if [ $? -eq 0 ]; then
    echo "✅ Pull successful, now pushing..."
    git push origin main
    
    if [ $? -eq 0 ]; then
        echo ""
        echo "✅✅✅ ALL CHANGES PUSHED TO PRODUCTION"
        echo ""
        echo "Bot will now:"
        echo "  • Enforce 8-position cap"
        echo "  • Require minimum \$2 positions"
        echo "  • Liquidate concurrently"
        exit 0
    else
        echo "❌ Push still failed after pull"
        exit 1
    fi
else
    echo "⚠️ Pull had conflicts or failed"
    echo "Attempting force push (use with caution)..."
    git push -f origin main
    exit $?
fi
