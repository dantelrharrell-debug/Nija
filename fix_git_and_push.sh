#!/bin/bash
set -e

echo "Configuring git user..."
git config user.email "dantelrharrell@users.noreply.github.com"
git config user.name "dantelrharrell-debug"
git config commit.gpgsign false

echo "Committing changes..."
git add bot.py bot/trading_strategy.py bot/nija_apex_strategy_v71.py bot/broker_manager.py

git commit -m "Fix API rate limiting and volume filters

- Increase scan interval from 15s to 30s (reduce API calls by 50%)
- Add price caching with 30s TTL to minimize redundant requests
- Implement exponential backoff retry logic (1s->2s->4s, 3 attempts)
- Lower volume thresholds: 50%->30% market filter, 30%->20% no-trade
- Resolves 'Could not get price' errors from rate limiting
- Enables more trade opportunities during low-volatility periods"

echo "Pushing to origin main..."
git push origin main

echo "✅ Successfully pushed all changes!"
