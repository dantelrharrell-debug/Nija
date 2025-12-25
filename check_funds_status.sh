#!/bin/bash
# NIJA Bot - Quick Balance Check and Fund Status
# Run this to see where your money is and what needs to be fixed

echo ""
echo "========================================================================"
echo "🔍 NIJA BALANCE & FUND STATUS CHECK"
echo "========================================================================"
echo ""

echo "1️⃣ Checking current balance location..."
echo "------------------------------------------------------------------------"
python3 check_balance_now.py

echo ""
echo ""
echo "2️⃣ Checking all portfolios for USD/USDC..."
echo "------------------------------------------------------------------------"
python3 find_funded_portfolio.py

echo ""
echo ""
echo "========================================================================"
echo "📊 DIAGNOSIS COMPLETE"
echo "========================================================================"
echo ""
echo "🎯 WHAT TO LOOK FOR:"
echo ""
echo "  ✅ GOOD: 'Advanced Trade USD: $XX.XX [TRADABLE]' where XX >= 50"
echo "  ⚠️  PROBLEM: 'Advanced Trade USD: $0.00' but 'Consumer USD: $XX.XX'"
echo "  ❌ CRITICAL: All balances show $0.00 or < $10"
echo ""
echo "🔧 NEXT STEPS:"
echo ""
echo "  IF balance < $10:"
echo "    → Read: cat FIX_INSUFFICIENT_FUNDS.md"
echo "    → Action: Deposit $50-$100 to Coinbase Advanced Trade"
echo ""
echo "  IF funds in Consumer wallet:"
echo "    → Option 1: Set ALLOW_CONSUMER_USD=true in .env"
echo "    → Option 2: Transfer to Advanced Trade via coinbase.com"
echo ""
echo "  IF balance >= $50:"
echo "    → You're ready to trade! Restart the bot."
echo ""
echo "========================================================================"
echo ""
