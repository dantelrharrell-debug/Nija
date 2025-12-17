#!/bin/bash
# Deploy Coinbase completion features: error handling + position persistence

set -e

echo "🚀 Deploying Coinbase completion features..."
echo ""
echo "✅ Features implemented:"
echo "   1. Fee tracking and reporting (DONE)"
echo "   2. Order fill verification with slippage detection (DONE)"
echo "   3. Performance analytics (win rate, P&L, fees) (DONE)"
echo "   4. Error handling for partial fills and retries (NEW)"
echo "   5. Trade history export to CSV/JSON (DONE)"
echo "   6. Position persistence for crash recovery (NEW)"
echo ""
echo "📦 New modules:"
echo "   - bot/position_manager.py (persistent position tracking)"
echo "   - bot/retry_handler.py (exponential backoff & partial fill handling)"
echo ""
echo "🔧 Updated files:"
echo "   - bot/trading_strategy.py (integrated retry + persistence)"
echo ""

# Add all changes
git add bot/position_manager.py \
        bot/retry_handler.py \
        bot/trading_strategy.py

# Commit with comprehensive message
git commit -m "🎯 Complete Coinbase integration - Error handling + Position persistence

NEW FEATURES:
✅ Exponential backoff retry (3 attempts with 2s/4s/8s delays)
✅ Partial fill detection and handling
✅ Network timeout recovery with automatic retries
✅ Order status verification after placement
✅ Position persistence to JSON (crash recovery)
✅ Load and validate positions on bot restart
✅ Atomic file writes for data safety

MODULES ADDED:
- bot/position_manager.py (219 lines)
  * Save/load positions from /usr/src/app/data/open_positions.json
  * Validate positions against broker API on startup
  * Handle positions closed externally
  * Atomic writes using temp file + rename
  
- bot/retry_handler.py (247 lines)
  * RetryHandler class with exponential backoff
  * Decorator for automatic retry on API failures
  * Partial fill detection (tolerance: 1%)
  * Order status verification (5 checks, 1s interval)
  * Rate limit detection (429, 503, 504 errors)

INTEGRATION POINTS:
- Entry orders: Wrapped in retry_on_failure decorator
- Exit orders: Wrapped in retry_on_failure decorator  
- Partial fill checks: Both entry and exit
- Position save: After every trade execution
- Position save: After every position close
- Position load: On bot startup with validation

ERROR HANDLING:
- Retryable errors: timeout, network, rate limit, 503/504
- Non-retryable: invalid, unauthorized, insufficient funds, 400/401/403
- Partial fills: Warning logged with filled percentage
- Corrupted position file: Backup to .corrupted extension

CRASH RECOVERY:
- Positions saved atomically after each trade
- Restored on bot restart
- Validated against current market data
- Invalid positions automatically removed

COINBASE INTEGRATION: ✅ COMPLETE
All 6 TODO items implemented:
1. ✅ Fee tracking (0.6% taker, 0.4% maker)
2. ✅ Fill price verification
3. ✅ Performance analytics  
4. ✅ Error handling & retries
5. ✅ Trade history export
6. ✅ Position persistence

READY FOR: Binance migration with same robust infrastructure
"

# Push to remote
echo ""
echo "📤 Pushing to Railway..."
git push origin main

echo ""
echo "✅ Deployment complete!"
echo ""
echo "🎉 COINBASE INTEGRATION COMPLETE!"
echo ""
echo "Next step: Binance integration with 6x cheaper fees (0.1% vs 0.6%)"
echo "           Same analytics architecture, just update fee constants"
echo "           Plus: 10x-125x leverage + SHORT position support"
echo ""
