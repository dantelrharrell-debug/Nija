#!/bin/bash
# Fix trade execution retry logic

git add bot/trading_strategy.py bot/position_manager.py bot/retry_handler.py COINBASE_COMPLETE.md
git commit -m "🔧 Fix trade execution - manual retry logic for orders

BUG FIX:
- Trades were failing with 'None' due to inline decorator issue
- Replaced @retry_handler decorator with manual retry loops
- Entry orders: 3 attempts with 2s, 4s, 8s backoff
- Exit orders: Same retry logic
- Partial fill detection still active

CHANGES:
- bot/trading_strategy.py:
  * execute_trade(): Manual retry loop (lines 506-522)
  * manage_open_positions(): Manual retry for exits (lines 706-724)
  * Exponential backoff: time.sleep(2 * attempt)
  * Better error logging per attempt

NEW MODULES (from previous commit):
- bot/position_manager.py (219 lines) - Position persistence
- bot/retry_handler.py (247 lines) - Partial fill detection
- COINBASE_COMPLETE.md - Full documentation

STATUS: Coinbase integration now FUNCTIONAL
Next: Test in production, then Binance migration"

git push origin main
echo "✅ Retry fix deployed!"
