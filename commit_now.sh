#!/bin/bash
set -e

echo "Configuring git..."
git config user.email "dantelrharrell@users.noreply.github.com"
git config user.name "dantelrharrell-debug"
git config commit.gpgsign false

echo "Staging bot files with changes..."
git add -f bot.py bot/trading_strategy.py bot/nija_apex_strategy_v71.py bot/broker_manager.py

echo "Committing..."
git commit -m "Fix API rate limiting and volume filters

- Scan interval: 15s -> 30s (50% reduction in API calls)
- Added price caching with 30s TTL
- Exponential backoff retry logic (1s->2s->4s, 3 attempts)
- Volume thresholds: 50%->30% market filter, 30%->20% no-trade
- Resolves 'Could not get price' errors
- Better trade opportunities in low-volatility"

echo "Pushing to origin main..."
git push origin main

echo "✅ Done!"
