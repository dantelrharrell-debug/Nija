#!/bin/bash

# Commit and push ultra aggressive filter changes for 15-day goal

git add bot/nija_apex_strategy_v71.py FILTER_ANALYSIS_15DAY_GOAL.md commit_filter_changes.sh

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

git push origin main

echo "✅ Commit and push completed!"
echo "Commit hash:"
git log -1 --oneline
