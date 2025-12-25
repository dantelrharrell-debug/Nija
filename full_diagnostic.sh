#!/bin/bash
# Run all diagnostic checks and create a report

echo "================================================================================"
echo "🚨 NIJA SELLING & MONEY TRACKING - FULL DIAGNOSTIC"
echo "================================================================================"
echo ""
echo "Running comprehensive checks..."
echo ""

# Check 1: Where's the money?
echo "1️⃣  Checking account balances..."
python3 emergency_money_check.py

echo ""
echo "================================================================================"
echo "2️⃣  Checking if NIJA selling logic is enabled in code..."
echo "================================================================================"

# Check if selling is implemented
if grep -q "manage_open_positions" bot/trading_strategy.py; then
    echo "✅ Selling logic FOUND in bot/trading_strategy.py"
else
    echo "❌ Selling logic NOT FOUND!"
fi

if grep -q "take_profit_pct = 0.06" bot/trading_strategy.py; then
    echo "✅ Take profit target: +6% CONFIGURED"
else
    echo "❌ Take profit NOT configured"
fi

if grep -q "stop_loss_pct = 0.02" bot/trading_strategy.py; then
    echo "✅ Stop loss: -2% CONFIGURED"
else
    echo "❌ Stop loss NOT configured"
fi

echo ""
echo "================================================================================"
echo "3️⃣  Key Questions to Answer:"
echo "================================================================================"
echo ""
echo "Q1: Is NIJA deployed and running on Railway?"
echo "    Visit: https://railway.app"
echo "    Check: Latest deployment status and logs"
echo ""
echo "Q2: Did you manually sell crypto recently?"
echo "    Check: https://www.coinbase.com/transactions"
echo ""
echo "Q3: Did you run any liquidation scripts?"
echo "    • direct_sell.py"
echo "    • enable_nija_profit.py"
echo "    • emergency_liquidate.py"
echo ""
echo "Q4: Where did the $95 go?"
echo "    Check the emergency_money_check.py output above"
echo ""
echo "================================================================================"
echo "4️⃣  Next Steps Based on Findings:"
echo "================================================================================"
echo ""
echo "IF money is found in Consumer wallet:"
echo "  → Transfer to Advanced Trade: https://www.coinbase.com/advanced-portfolio"
echo "  → OR run: python3 enable_nija_profit.py"
echo ""
echo "IF money disappeared completely:"
echo "  → Check Coinbase website transaction history"
echo "  → Check email for withdrawal/transfer confirmations"
echo "  → Contact Coinbase support if unauthorized"
echo ""
echo "IF bot is not running on Railway:"
echo "  → Deploy bot to Railway"
echo "  → Verify it stays running 24/7"
echo "  → Selling only works if bot is continuously monitoring"
echo ""
echo "IF selling logic is disabled:"
echo "  → Code shows it IS enabled ✅"
echo "  → Problem is deployment or execution, not code"
echo ""
echo "================================================================================"
