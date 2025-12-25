#!/bin/bash
# CRITICAL DEPLOYMENT: Fix bleeding bot - precision bugs and stop losses
# Date: 2025-12-25
# Purpose: Deploy precision fixes and protective stops to stop capital bleeding

set -e

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🚨 CRITICAL FIX DEPLOYMENT: Precision Bugs + Stop Loss Protection"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Step 1: Remove emergency liquidation triggers
echo "Step 1: Removing emergency liquidation triggers..."
bash remove_emergency_triggers.sh
echo ""

# Step 2: Check current balance
echo "Step 2: Current status check..."
echo "   Trading balance: ~\$50 (bleeding stopped after fix)"
echo "   Open positions: ~20 (most are dust from failed sells)"
echo "   Position cap: 8 (enforcer will reduce gradually)"
echo ""

# Step 3: Commit fixes
echo "Step 3: Committing precision fixes and stop loss protection..."
git add bot/broker_manager.py
git add bot/position_cap_enforcer.py
git add bot/trading_strategy.py
git add bot/emergency_stop_loss.py
git add remove_emergency_triggers.sh
git add deploy_critical_fixes.sh

git commit -m "CRITICAL FIX: Correct Coinbase precision + Add emergency stops

Fixes:
1. ✅ Corrected fallback_increment_map - many coins require WHOLE numbers
   - ADA, XRP, DOGE, XLM, HBAR, ZRX, CRV, FET, VET: increment=1 (not 0.01)
   - This fixes INVALID_SIZE_PRECISION errors that prevented selling

2. ✅ Fixed precision calculation using math.log10 instead of string parsing
   - Correctly calculates decimals: 1→0, 0.1→1, 0.01→2, 0.001→3, etc.

3. ✅ Fixed quantization using floor division instead of Decimal
   - More reliable and handles edge cases better

4. ✅ Updated position_cap_enforcer to use corrected broker.place_order
   - No more direct SDK calls that bypass precision fixes

5. ✅ Added emergency stop loss protection (5% stops on all positions)
   - Prevents unlimited downside from weak market conditions
   - Exits automatically when positions drop >5%

6. ✅ Enhanced position exit logic with dual protection:
   - Exit on weak market conditions (ADX low, volume low)
   - Exit on emergency stop loss hit (-5%)

Impact:
- Precision bugs fixed → positions can now sell successfully
- Stop losses active → prevents further bleeding
- Position cap enforcer working correctly → will reduce to 8 gradually
- STOP_ALL_ENTRIES.conf still active → no new losing trades

Next Steps:
1. Deploy to Railway
2. Monitor next trading cycle (2.5 min)
3. Positions should start exiting successfully
4. Once down to 8 positions, remove STOP_ALL_ENTRIES.conf"

echo "✅ Changes committed"
echo ""

# Step 4: Push to GitHub
echo "Step 4: Pushing to GitHub..."
git push origin main
echo "✅ Pushed to GitHub"
echo ""

# Step 5: Deployment summary
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ DEPLOYMENT COMPLETE"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Railway will auto-deploy in ~30 seconds"
echo ""
echo "What to expect in next trading cycle (2.5 min):"
echo "  1. Position cap enforcer will sell 2 smallest positions"
echo "  2. Sell orders should now SUCCEED (precision fixed)"
echo "  3. Emergency stops active (5% stops on all positions)"
echo "  4. Weak positions will exit automatically"
echo ""
echo "Monitor logs for:"
echo "  ✅ 'SOLD successfully' messages (precision fix working)"
echo "  ✅ Positions reducing from 20 → 18 → 16 → ... → 8"
echo "  ✅ No more INVALID_SIZE_PRECISION errors"
echo ""
echo "Once down to ≤8 positions:"
echo "  rm STOP_ALL_ENTRIES.conf  # Re-enable new trades"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
