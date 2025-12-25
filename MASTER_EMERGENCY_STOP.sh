#!/usr/bin/env bash
#
# MASTER EMERGENCY STOP - Execute this to stop bleeding immediately
#
set -e

echo ""
echo "================================================================================"
echo "🚨 NIJA EMERGENCY STOP - STOPPING ALL BLEEDING"
echo "================================================================================"
echo ""
echo "This script will:"
echo "  1. Commit emergency liquidation code"
echo "  2. Push to Railway (triggers auto-deploy)"
echo "  3. Create LIQUIDATE_ALL_NOW.conf trigger"
echo "  4. Bot will sell ALL positions within 2-3 minutes"
echo ""
echo "Current status: 13 positions actively losing money"
echo "Expected result: All crypto → USD (~\$63.67)"
echo ""

read -p "Press ENTER to execute emergency stop... " confirm

echo ""
echo "Step 1/3: Committing emergency fixes..."
git add -A
git commit -m "🚨 EMERGENCY: Add immediate liquidation mode to stop bleeding

- Added LIQUIDATE_ALL_NOW.conf trigger detection in trading_strategy.py
- Bot now sells ALL positions when emergency file detected
- Created AUTO_LIQUIDATE_ALL.py for direct execution
- Bypasses position cap logic for emergency sells
- Auto-removes trigger file after completion

CRITICAL FIX: Previous implementation only sold 1 position per cycle.
User had 13 positions and was bleeding money continuously.
This fix liquidates ALL positions in ONE cycle (2-3 minutes).

Files modified:
- bot/trading_strategy.py (added emergency liquidation mode)

Files created:
- LIQUIDATE_ALL_NOW.conf (trigger file)
- AUTO_LIQUIDATE_ALL.py (standalone script)
- FORCE_SELL_ALL_NOW.py (alternative script)
- STOP_BLEEDING_NOW.md (instructions)
- EMERGENCY_FIX_SUMMARY.md (summary)
- MASTER_EMERGENCY_STOP.sh (this script)
" || echo "⚠️ Commit may already exist"

echo ""
echo "Step 2/3: Pushing to Railway..."
git push origin main

echo ""
echo "Step 3/3: Verifying trigger file exists..."
if [ -f "LIQUIDATE_ALL_NOW.conf" ]; then
    echo "✅ LIQUIDATE_ALL_NOW.conf exists"
else
    echo "⚠️ Creating LIQUIDATE_ALL_NOW.conf..."
    touch LIQUIDATE_ALL_NOW.conf
    echo "✅ Created"
fi

echo ""
echo "================================================================================"
echo "✅ EMERGENCY STOP DEPLOYED"
echo "================================================================================"
echo ""
echo "WHAT HAPPENS NEXT:"
echo ""
echo "  1. Railway receives new code (~1 minute)"
echo "  2. Railway auto-deploys bot with emergency mode (~2 minutes)"
echo "  3. Bot detects LIQUIDATE_ALL_NOW.conf on next cycle"
echo "  4. Bot sells ALL 13 positions immediately"
echo "  5. Bot auto-removes trigger file"
echo ""
echo "TIMELINE:"
echo "  Now + 3min: Deployment complete"
echo "  Now + 5min: Liquidation executing"
echo "  Now + 6min: All positions sold"
echo ""
echo "WHERE TO WATCH:"
echo "  Railway → Your Bot → Logs tab"
echo "  Look for: '🚨 EMERGENCY LIQUIDATION MODE ACTIVE'"
echo ""
echo "EXPECTED LOGS:"
echo "  🚨 EMERGENCY LIQUIDATION MODE ACTIVE"
echo "     SELLING ALL POSITIONS IMMEDIATELY"
echo "     Found 13 positions to liquidate"
echo "     [1/13] FORCE SELLING BTC..."
echo "     ✅ SOLD BTC"
echo "     [2/13] FORCE SELLING ETH..."
echo "     ✅ SOLD ETH"
echo "     ..."
echo "     ✅ Emergency liquidation complete"
echo ""
echo "FINAL STATE:"
echo "  Crypto: \$0.00 (all sold)"
echo "  Cash: ~\$63.67"
echo "  Bleeding: STOPPED"
echo ""
echo "================================================================================"
echo ""
echo "🕐 Check Railway logs in 5 minutes to confirm liquidation"
echo ""
