#!/bin/bash
# Commit and push all changes

echo "📝 Adding all changes..."
git add -A

echo "💾 Committing..."
git commit -m "Add comprehensive balance check, auto-sell crypto, and path to \$1000/day analysis tools

- Created assess_goal_now.py: Full balance check with goal assessment
- Created auto_sell_all_crypto.py: Auto-liquidate all crypto positions  
- Created force_check_and_sell.py: Check all accounts and sell crypto
- Created PATH_TO_1000_A_DAY.py: Calculate realistic path to \$1000/day earnings
- Created check_and_sell_all.py: Interactive crypto liquidation tool
- Created full_status_check.py: Comprehensive status check script
- Created check_now.py: Quick balance diagnostic
- Created RUN_GOAL_CHECK.sh: Quick goal assessment runner
- Created RUN_SELL_ALL.sh: Auto-sell and balance check runner
- Created AUTO_SELL_AND_LIVING_WAGE_ANALYSIS.md: Complete analysis documentation

All tools support \$115 starting balance, show realistic timeline to living wage (7-10 months),
highlight Coinbase fee issues (4-6% vs Binance 0.2%), and provide actionable next steps.

Analysis shows:
- With 10% daily net: reach \$1000/day capital in 85 days (2.8 months)
- With 15% daily net: reach \$1000/day capital in 42 days (1.4 months)
- NIJA already has auto-sell built-in (no code changes needed)
- Switching to Binance cuts timeline in half (0.2% fees vs 4-6%)
"

echo "🚀 Pushing to GitHub..."
git push origin main

echo "✅ Done!"
