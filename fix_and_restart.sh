#!/bin/bash
set -e

cd /workspaces/Nija

echo "🔧 Committing position size fix..."
git add bot/adaptive_growth_manager.py

git commit -m "Fix: Add missing get_position_size_pct() method to AdaptiveGrowthManager

ERROR FIXED:
- AdaptiveGrowthManager was missing get_position_size_pct() method
- Bot could find signals but couldn't execute trades
- Added method to return position size based on growth stage

FUNCTIONALITY:
- Ultra aggressive mode: 40% position size (maximize growth)
- Aggressive mode: 30% position size  
- Moderate mode: 20% position size
- Conservative mode: 15% position size

With \$57.54 balance:
- Ultra aggressive stage (< \$300)
- Position size: 40% = \$23.02 per trade
- After Coinbase \$5 minimum, will execute trades properly

This allows bot to:
1. Execute trades on buy signals
2. Manage existing positions with sell logic
3. Make profits with proper position sizing"

git push origin main

echo ""
echo "✅ Fix committed and pushed!"
echo ""
echo "🚀 Restarting bot to start trading..."
echo ""

export ALLOW_CONSUMER_USD=true
export LIVE_TRADING=1

exec ./start.sh
