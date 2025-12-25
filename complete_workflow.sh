#!/bin/bash
# COMPLETE WORKFLOW: Sell crypto, commit, check balance, decide next steps

echo "=================================================================="
echo "🚀 NIJA BOT: SELL CRYPTO & REACH \$100 WORKFLOW"
echo "=================================================================="
echo ""

# Step 1: Sell all crypto
echo "STEP 1: SELLING ALL CRYPTO POSITIONS"
echo "------------------------------------------------------------------"
python3 sell_crypto_now.py

echo ""
echo ""

# Step 2: Commit all changes
echo "STEP 2: COMMITTING ALL FIXES TO GIT"
echo "------------------------------------------------------------------"
bash commit_everything.sh

echo ""
echo ""

# Step 3: Show final instructions
echo "STEP 3: NEXT STEPS BASED ON YOUR BALANCE"
echo "------------------------------------------------------------------"
echo ""
echo "Check the output above to see your USD balance after selling crypto."
echo ""
echo "=================================================================="
echo "📊 DECISION TREE"
echo "=================================================================="
echo ""
echo "IF YOU HAVE \$0-40:"
echo "   ❌ Don't trade - deposit \$60-160 instead"
echo "   💰 Run: [Deposit to Coinbase] then python3 main.py"
echo ""
echo "IF YOU HAVE \$40-70:"
echo "   ⚠️  RISKY - 20% success rate"
echo "   ✅ RECOMMENDED: Deposit \$30-60 to reach \$100"
echo "   ⚠️  OR TRY ANYWAY: python3 main.py (small-cap mode)"
echo ""
echo "IF YOU HAVE \$70-90:"
echo "   ✅ VIABLE - 60% success rate"
echo "   💡 SAFER: Deposit \$10-30 to hit \$100"
echo "   ✅ OR TRADE: python3 main.py (conservative mode)"
echo ""
echo "IF YOU HAVE \$90-100+:"
echo "   ✅ PERFECT - You're at goal!"
echo "   🚀 START BOT: python3 main.py"
echo ""
echo "=================================================================="
echo ""
echo "📖 FOR COMPLETE DETAILS:"
echo "   Read: FINAL_INSTRUCTIONS.md"
echo "   Read: CAN_I_REACH_100.md"
echo "   Read: PROFITABILITY_REALITY_CHECK.md"
echo ""
echo "=================================================================="
echo ""
