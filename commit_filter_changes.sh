#!/bin/bash
# Deploy relaxed filters for 15-day goal

echo "🚀 Committing filter changes for ULTRA AGGRESSIVE 15-day mode..."

# Stage changes
git add bot/nija_apex_strategy_v71.py
git add FILTER_ANALYSIS_15DAY_GOAL.md
git add commit_filter_changes.sh

# Commit with detailed message
git commit -m "ULTRA AGGRESSIVE MODE: Relax all filters for 15-day goal

Changes to nija_apex_strategy_v71.py:
- Market filter: 3/5 → 1/5 conditions required
- Entry signals: 3/5 → 1/5 conditions required  
- ADX check: Bypass when min_adx=0
- Volume check: Bypass when threshold=0.0

EXPECTED IMPACT:
- 10-25 trade signals per cycle (vs 0 currently)
- 600-1000 trades/hour potential

15-DAY GOAL: \$55.81 → \$111.62 (100% growth)"

# Push to trigger Railway rebuild
git push origin main

echo ""
echo "✅ Changes pushed! Railway will rebuild automatically."
echo ""
echo "📝 Commit hash:"
git log -1 --oneline
echo ""
echo "📊 Monitor Railway logs for trade signals in next cycle (~15 seconds)"
