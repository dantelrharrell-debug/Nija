#!/bin/bash
set -e

echo "🔧 Configuring git..."
git config user.email "dantelrharrell@users.noreply.github.com"
git config user.name "dantelrharrell-debug"
git config commit.gpgsign false

echo "📝 Staging all bot code changes..."
git add -A

echo "💾 Committing with detailed message..."
git commit -m "Complete API optimization deployment - caching + retry + volume filters

PRIMARY FIXES:
✅ Price caching (30s TTL) - reduces redundant API calls
✅ Exponential backoff retry (1s→2s→4s, 3 attempts) - handles rate limits gracefully  
✅ Volume filter optimization (50%→30%, 30%→20%) - captures more opportunities
✅ Scan interval 30s (already deployed) - 50% fewer API calls

TECHNICAL CHANGES:
- bot/trading_strategy.py: Added _price_cache, _cache_timestamp, _cache_ttl
- bot/trading_strategy.py: Modified fetch_candles() to check cache before API call
- bot/trading_strategy.py: Cache cleared at start of each run_cycle()
- bot/broker_manager.py: Wrapped get_candles() in retry loop with exponential backoff
- bot/nija_apex_strategy_v71.py: volume_threshold 0.5→0.3, volume_min_threshold 0.3→0.2

EXPECTED OUTCOMES:
- Eliminate 'Could not get price' errors via retry mechanism
- Reduce API call frequency by ~60-70% via caching + 30s interval
- Increase trade signal capture rate by 2-3x via lower volume thresholds
- Graceful degradation during API rate limit periods

Resolves: API rate limiting blocking 70%+ of Day 1 trades" || echo "Nothing new to commit"

echo "🚀 Pushing to Railway..."
git push origin main

echo ""
echo "✅ DEPLOYMENT COMPLETE!"
echo "Monitor Railway logs for:"
echo "  - Fewer 'Could not get price' errors"
echo "  - More BUY/SELL signals appearing"  
echo "  - Position management working smoothly"
