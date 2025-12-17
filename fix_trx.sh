#!/bin/bash
# Remove invalid TRX-USD pair from curated market list

git add bot/trading_strategy.py
git commit -m "🔧 Remove invalid TRX-USD from curated markets (49 pairs now)

- TRX-USD returns 400 'ProductID is invalid' errors
- Reduced from 50 to 49 markets
- All other pairs validated and working"
git push origin main

echo "✅ Fix deployed - TRX-USD removed"
echo "🔄 Railway will auto-rebuild in ~1-2 minutes"
