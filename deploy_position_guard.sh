#!/bin/bash
cd /workspaces/Nija
git add bot/trading_strategy.py
git commit -m "Add live position count enforcement to prevent buys when at limit

CRITICAL FIX: Bot was immediately buying new positions after user manual sells
because it only checked in-memory tracker, not actual Coinbase holdings.

Changes:
- Added real-time Coinbase position count check before ANY buy
- Blocks BUYs when actual crypto holdings >= max_concurrent_positions (8)
- Prevents bot from re-using freed USD when user manually liquidates
- Fail-safe: blocks buy if can't verify position count

This works alongside MIN_CASH_TO_BUY to create dual protection:
1. Position count must be < 8
2. USD balance must be >= \$5.00

Both conditions must pass for bot to execute a buy."
git push origin main
echo "✅ Changes committed and pushed"
