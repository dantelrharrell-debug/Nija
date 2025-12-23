#!/bin/bash
# Deploy profitability-first trading filters

echo "🎯 DEPLOYING: PROFITABILITY-FIRST TRADING MODE"
echo "=============================================="
echo ""
echo "NEW ENTRY FILTERS:"
echo "  ❌ RSI > 70 (overbought - will reverse)"
echo "  ❌ Score < 70 (low probability signals)"
echo "  ❌ Price near 20-candle high (chasing tops)"
echo "  ❌ Quality score < 70 in execute_trade"
echo "  ✅ Only buy strong dips in confirmed uptrends"
echo ""
echo "BENEFIT:"
echo "  → Fewer losing trades"
echo "  → Higher win rate"
echo "  → Better entries = better exits"
echo ""

git add bot/trading_strategy.py sell_losing_positions.py
git commit -m "PROFITABILITY MODE: Only buy high-probability winning trades

USER REQUEST: Stop buying losing trades, only buy profitable setups

CHANGES:
1. RSI overbought filter (> 70) - blocks buying at peaks
2. Minimum score requirement (>= 70) - only high-quality signals
3. Recent high filter - don't chase, wait for dips
4. Double quality check in execute_trade
5. Raised MIN_CASH_TO_BUY to \$10 for better entries

ENTRY REQUIREMENTS (ALL MUST PASS):
✅ Uptrend confirmed
✅ RSI < 70 (not overbought)  
✅ Score >= 70 (high probability)
✅ Price NOT within 2% of 20-candle high
✅ USD balance >= \$10

RESULT:
- Far fewer entries (quality over quantity)
- Higher win rate expected
- No more buying tops that immediately reverse
- Only trades with strong setup confirmation

Also added: sell_losing_positions.py script for cleanup"

git push origin main

echo ""
echo "✅ DEPLOYED! Bot will now be EXTREMELY selective."
echo "   Expect fewer trades but much higher quality."
