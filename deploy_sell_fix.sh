#!/bin/bash
# Deploy critical sell order fix

cd /workspaces/Nija

echo "📦 Staging sell order fix..."
git add bot/trading_strategy.py

echo "✅ Committing..."
git commit -m "CRITICAL FIX: Implement sell orders for take-profit and stop-loss exits

- Added market_order_sell() execution in close_partial_position() for TP1/TP2 exits
- Added market_order_sell() execution in close_full_position() for stop-loss/final exits
- Calculates correct crypto base_size from position['size'] * remaining_size
- Validates position exists before attempting close
- Adds error handling with detailed logging for sell failures
- Both LIVE and PAPER modes now fully functional

Issue: Bot was detecting signals and managing positions but not executing sell orders
Root Cause: Sell order logic was stubbed with 'pass' instead of actual API calls
Impact: All profits were unrealized - positions never closed on Railway
Fix: Uses client.market_order_sell() with base_size parameter matching Coinbase API"

echo "🚀 Pushing to GitHub..."
git push

echo "✅ Done! Railway will auto-deploy with sell functionality in ~30 seconds"
