#!/bin/bash
cd /workspaces/Nija

echo "📝 Staging changes..."
git add bot/trading_strategy.py bot/indicators.py bot/broker_manager.py

echo "✍️  Committing..."
git commit -m "Fix indicator calculation and balance logging

- Add numeric coercion in fetch_candles() to prevent str/int division
- Add _ensure_numeric() guard across all indicator helpers  
- Add detailed balance fetch logging to debug \$0.00 issue
- Drop invalid candle rows before indicator math"

echo "🚀 Pushing to origin/main..."
git push origin main

echo "✅ Done!"
git log --oneline -1
