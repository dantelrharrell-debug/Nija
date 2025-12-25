#!/bin/bash
# Force Railway to rebuild with the _price_cache fix
# Railway is still running old code - force fresh deployment

set -e

echo "========================================"
echo "🚨 FORCE RAILWAY REDEPLOY"
echo "========================================"
echo ""
echo "Issue: Railway is running OLD code"
echo "  - Fix is committed locally"
echo "  - But Railway didn't rebuild"
echo "  - Still showing _price_cache errors"
echo ""

cd /workspaces/Nija

# Create empty trigger file to force rebuild
touch .railway-rebuild-$(date +%s)

# Stage all changes including the fix
git add -A

# Commit with force rebuild flag
git commit -m "🚨 FORCE REBUILD: Fix _price_cache initialization (Railway cache bust)

Railway is running stale code despite previous push.

Changes:
- trading_strategy.py: Move _price_cache init to line 123 (BEFORE sync)
- Previous location: line 261 (AFTER sync)
- This fixes: AttributeError on all 15 position syncs

Force rebuild to clear Railway cache." --allow-empty

echo ""
echo "🚀 Force pushing to Railway..."
git push origin main --force-with-lease

echo ""
echo "========================================"
echo "✅ FORCE REBUILD TRIGGERED"  
echo "========================================"
echo ""
echo "Railway will do a FRESH rebuild (2-3 min)"
echo ""
echo "After rebuild, logs should show:"
echo "  ✅ Synced LTC-USD: entry=\$76.67"
echo "  ✅ Synced ETH-USD: entry=\$2977"
echo "  ✅ Synced SOL-USD: entry=\$185"
echo "  (NO MORE _price_cache ERRORS)"
echo ""
echo "Monitor: https://railway.app/dashboard"
echo "========================================"
