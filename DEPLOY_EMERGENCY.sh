#!/bin/bash
# EMERGENCY DEPLOYMENT - Account at $40 and bleeding

set -e

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🚨 EMERGENCY: Account at \$40 - Deploying critical fixes NOW"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Remove emergency triggers
echo "Step 1: Removing emergency liquidation triggers..."
rm -f LIQUIDATE_ALL_NOW.conf FORCE_LIQUIDATE_ALL_NOW.conf FORCE_EXIT_ALL.conf FORCE_EXIT_EXCESS.conf FORCE_EXIT_OVERRIDE.conf
echo "✅ Emergency triggers removed"
echo ""

# Stage all changes
echo "Step 2: Staging all changes..."
git add -A
echo "✅ All changes staged"
echo ""

# Commit with the prepared message
echo "Step 3: Committing critical fixes..."
git commit -F .git/COMMIT_EDITMSG
echo "✅ Changes committed"
echo ""

# Push to GitHub
echo "Step 4: Pushing to GitHub..."
git push origin main
echo "✅ Pushed to GitHub - Railway will auto-deploy in ~30 seconds"
echo ""

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ DEPLOYMENT COMPLETE"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "WHAT HAPPENS NEXT:"
echo "  1. Railway detects push and starts deployment (~30 seconds)"
echo "  2. New code deploys with precision fixes"
echo "  3. Next trading cycle (2.5 min): Sells should SUCCEED"
echo "  4. Position count decreases: 20 → 18 → 16 → ... → 8"
echo "  5. Bleeding STOPS (5% max loss per position)"
echo ""
echo "MONITOR:"
echo "  - Railway deployment logs"
echo "  - Look for: 'SOLD successfully' messages"
echo "  - Watch: Position count decreasing"
echo "  - Confirm: No INVALID_SIZE_PRECISION errors"
echo ""
echo "CRITICAL: Watch next 3 trading cycles (7.5 minutes)"
echo "If sells succeed → bleeding stopped ✅"
echo "If sells fail → check logs for new error types ❌"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
