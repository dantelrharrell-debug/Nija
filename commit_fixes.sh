#!/bin/bash
set -e

echo "Staging modified files..."
git add bot.py bot/trading_strategy.py bot/nija_apex_strategy_v71.py bot/broker_manager.py

echo "Committing changes..."
git commit -m "Fix API rate limiting and volume filters

- Increase scan interval from 15s to 30s to reduce API calls by 50%
- Add price data caching (30s TTL) to minimize redundant API requests  
- Implement exponential backoff retry logic for API rate limits (3 retries, 1s->2s->4s)
- Lower volume thresholds: 50%->30% for market filter, 30%->20% for no-trade
- Improves trade opportunities during low-volatility periods
- Resolves 'Could not get price' errors from excessive API usage

Changes target Day 1 issues: API rate limiting blocking 70% of trades
Expected impact: Better trade execution, fewer missed opportunities"

echo "Pushing to origin main..."
git push origin main

echo "✅ All changes pushed successfully!"
