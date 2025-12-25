#!/bin/bash
set -e

cd /workspaces/Nija

echo "========================================"
echo "🔧 FIXING SELL EXECUTION ERRORS"
echo "========================================"
echo ""
echo "Issue: Sells not executing when emergency stop active"
echo "Fix: Enhanced logging + fallback price fetch"
echo ""

git add -A
git commit -F COMMIT_SELL_FIX.txt
git push origin main

echo ""
echo "========================================"
echo "✅ FIX PUSHED TO GITHUB"
echo "========================================"
echo ""
echo "Railway will rebuild in 1-2 minutes."
echo "Check logs for:"
echo "  - '✅ Fallback price fetch succeeded' (indicates sell retry working)"
echo "  - '📊 Managing N open position(s)' (indicates positions being checked)"
echo "========================================"
