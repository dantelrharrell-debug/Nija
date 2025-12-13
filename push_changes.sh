#!/bin/bash
cd /workspaces/Nija
git add -A
git commit -m 'Refactor balance tracking and candle normalization

- Update get_account_balance() to include USD + USDC balance
- Add _normalize_candles() helper for early type conversion
- Replace pd.to_numeric() with .astype(float) for better clarity
- Improve error handling with logger instead of print statements'
git push origin main
echo "✅ Changes pushed to main"
