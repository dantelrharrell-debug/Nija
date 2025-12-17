#!/bin/bash
cd /workspaces/Nija
git add -A
git commit -m "🚫 Disable SHORT selling - Coinbase spot doesn't support it

- Commented out SELL signal generation for downtrends  
- CRV-USD was generating SHORT signals that failed with 400 errors
- Coinbase Advanced Trade API only supports LONG (BUY) positions on spot markets
- Bot will now only execute BUY trades, no more failed SELL attempts
- TRX-USD fix confirmed working (49 markets, no 400 errors)
- 8 concurrent positions trading successfully"
git push origin main
echo "✅ Deployed - SHORT selling disabled"
