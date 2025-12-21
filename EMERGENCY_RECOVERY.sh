#!/bin/bash
# 🚨 EMERGENCY RECOVERY SCRIPT - RUN THIS IMMEDIATELY
# This script will:
# 1. Diagnose what's actually wrong
# 2. Force-sell everything to stop losses
# 3. Reset bot state for fresh start
# 4. Disable auto-trading until fixes are made

set -e

echo ""
echo "╔═══════════════════════════════════════════════════════════════════════════════╗"
echo "║                   🚨 NIJA EMERGENCY RECOVERY PROCEDURE                         ║"
echo "╚═══════════════════════════════════════════════════════════════════════════════╝"
echo ""

# Step 1: Diagnose
echo ""
echo "STEP 1️⃣  - DIAGNOSTIC: What's actually in your account?"
echo "═══════════════════════════════════════════════════════════════════════════════════"
echo ""
echo "Running: python3 diagnose_holdings_now.py"
echo "This will show you:"
echo "  • What NIJA thinks it owns (from saved state)"
echo "  • What Coinbase actually shows"
echo "  • Where the mismatch is"
echo ""
python3 diagnose_holdings_now.py

echo ""
echo ""
echo "STEP 2️⃣  - DECISION: What do you want to do?"
echo "═══════════════════════════════════════════════════════════════════════════════════"
echo ""
echo "Option A: Emergency Liquidate ALL crypto immediately"
echo "         (Stops all losses RIGHT NOW, accepts current value)"
echo "         Command: python3 emergency_sell_all_now.py"
echo ""
echo "Option B: Fix orphaned positions (manual + bot state mismatch)"
echo "         (More surgical - only sells positions bot doesn't know about)"
echo "         Command: python3 force_fix_orphaned_positions.py"
echo ""
echo "Option C: Manual intervention"
echo "         (Go to coinbase.com web interface and sell manually)"
echo ""
read -p "Which option (A/B/C)? " choice

case $choice in
    A)
        echo ""
        echo "Running OPTION A: Emergency liquidate everything"
        echo "───────────────────────────────────────────────"
        python3 emergency_sell_all_now.py
        ;;
    B)
        echo ""
        echo "Running OPTION B: Fix orphaned positions"
        echo "───────────────────────────────────────────────"
        python3 force_fix_orphaned_positions.py
        ;;
    C)
        echo ""
        echo "OPTION C selected: Manual intervention"
        echo "───────────────────────────────────────────────"
        echo "Go to: https://www.coinbase.com/advanced-portfolio"
        echo "Sell all positions manually"
        echo "Then run: rm data/open_positions.json"
        ;;
    *)
        echo "Invalid choice"
        exit 1
        ;;
esac

echo ""
echo ""
echo "STEP 3️⃣  - RESET: Clear bot state"
echo "═══════════════════════════════════════════════════════════════════════════════════"
echo ""
echo "Resetting position file to empty..."
mkdir -p data
cat > data/open_positions.json << 'EOF'
{
  "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%S.%f)",
  "positions": {},
  "count": 0,
  "note": "Cleared during emergency recovery"
}
EOF
echo "✅ Position file cleared"

echo ""
echo ""
echo "STEP 4️⃣  - VERIFY: Check final state"
echo "═══════════════════════════════════════════════════════════════════════════════════"
echo ""
echo "Your account should now be:"
echo "  ✅ 100% cash (all crypto liquidated)"
echo "  ✅ Bot position file reset (empty)"
echo "  ✅ Ready for fresh start when issues are fixed"
echo ""
echo "Run again to verify:"
echo "  python3 diagnose_holdings_now.py"
echo ""

echo ""
echo "╔═══════════════════════════════════════════════════════════════════════════════╗"
echo "║                        ⚠️ DO NOT RESTART NIJA YET                              ║"
echo "╚═══════════════════════════════════════════════════════════════════════════════╝"
echo ""
echo "The bot's exit system is BROKEN - it won't reliably sell positions."
echo ""
echo "⏸️ STOP: Before restarting bot, we need to fix:"
echo ""
echo "1. Exit execution layer (detects exit conditions but doesn't execute sells)"
echo "2. Position state sync (ensure bot knows what it actually owns)"
echo "3. Order confirmation (verify sells actually filled)"
echo ""
echo "📋 Read ROOT_CAUSE_ANALYSIS.md for full technical breakdown"
echo ""
echo "✅ Once code fixes are implemented, you can safely restart trading"
echo ""
