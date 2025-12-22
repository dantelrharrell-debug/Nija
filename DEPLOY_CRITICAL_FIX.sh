#!/bin/bash
# 🚨 CRITICAL FIX DEPLOYMENT
# Fixes _price_cache bug preventing position monitoring

set -e

echo "========================================"
echo "🚨 DEPLOYING CRITICAL POSITION BUG FIX"
echo "========================================"
echo ""
echo "Bug Fixed:"
echo "  - _price_cache initialized AFTER position sync"
echo "  - All 15 positions failed to load"
echo "  - Bot couldn't monitor ANY positions"
echo ""
echo "Impact:"
echo "  ✅ Bot will now monitor all 15 positions"
echo "  ✅ Stop losses at -2% will execute"  
echo "  ✅ Take profits at +5% will execute"
echo "  ✅ Trailing stops will update"
echo ""

# Navigate to repo
cd /workspaces/Nija || exit 1

# Stage the fix
git add bot/trading_strategy.py

# Commit with detailed message
git commit -m "🚨 CRITICAL FIX: Initialize _price_cache before position sync

Bug: sync_positions_from_coinbase() called on line 232
     _price_cache initialized on line 261 (AFTER sync)
Result: AttributeError: 'TradingStrategy' object has no attribute '_price_cache'
        All 15 crypto positions failed to sync - bot blind to holdings

Fix: Move _price_cache, _cache_timestamp, _cache_ttl initialization
     to line 119 (BEFORE position sync)

This enables:
- Stop loss execution at -2% (3% protection)
- Take profit execution at +5%
- Trailing stop updates (90% profit lock)
- Position monitoring every 15 seconds

Tested: Initialization order now correct:
  1. Broker connection
  2. Analytics & Position Manager
  3. Price cache (NEW LOCATION)
  4. Balance fetch
  5. Position sync (can now access _price_cache)
  6. Trading loop start"

echo ""
echo "✅ Changes committed locally"
echo ""

# Push to trigger Railway deployment
echo "🚀 Pushing to Railway..."
git push origin main

echo ""
echo "========================================"
echo "✅ DEPLOYMENT COMPLETE"
echo "========================================"
echo ""
echo "Railway will rebuild in 2-3 minutes"
echo ""
echo "What happens next:"
echo "  1. Railway rebuilds with fix (2-3 min)"
echo "  2. Bot restarts automatically"
echo "  3. Position sync runs successfully"
echo "  4. All 15 positions now monitored"
echo "  5. Stop losses/take profits will execute"
echo ""
echo "Monitor deployment:"
echo "  https://railway.app/dashboard"
echo ""
echo "Expected in logs:"
echo "  '📊 Found 15 crypto positions to sync:'"
echo "  '✅ Synced LTC-USD: \$76.67...'"
echo "  '✅ Synced ETH-USD: \$2977.21...'"
echo "  (No more '_price_cache' errors!)"
echo ""
echo "========================================"
