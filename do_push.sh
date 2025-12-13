#!/bin/bash
set -e
cd /workspaces/Nija
git status
git add bot/broker_manager.py bot/trading_strategy.py
git commit -m "Refactor balance tracking and candle normalization

- Update get_account_balance() to include USD + USDC balance
- Add _normalize_candles() helper for early type conversion
- Replace pd.to_numeric() with .astype(float) for better clarity"
git push origin main
echo "✅ Done"
