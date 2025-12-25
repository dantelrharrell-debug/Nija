#!/bin/bash
set -e

echo "========================================"
echo "🚨 CRITICAL FIX: UNBLOCKING SELL EXITS"
echo "========================================"
echo ""
echo "Issue: FORCE_EXIT_ALL.conf causing early return"
echo "Impact: manage_open_positions() never runs"
echo "Fix: Remove early return, allow position management"
echo ""

cd /workspaces/Nija
git add -A
git commit -F COMMIT_CRITICAL_FIX.txt
git push origin main

echo ""
echo "========================================"
echo "✅ CRITICAL FIX DEPLOYED"
echo "========================================"
echo ""
echo "Railway will rebuild in ~60 seconds."
echo ""
echo "VERIFY IN LOGS:"
echo "  1. Look for: '📊 Managing 12 open position(s)'"
echo "  2. Check for price fetch attempts for each symbol"
echo "  3. Confirm sell orders execute when SL/TP hit"
echo ""
echo "If positions still don't sell:"
echo "  - Delete FORCE_EXIT_ALL.conf manually in Railway"
echo "  - Check stop loss/take profit levels are correctly set"
echo "========================================"
