#!/bin/bash
git add bot/broker_manager.py
git commit -m "FIX: Honor ALLOW_CONSUMER_USD flag to enable Consumer wallet trading

- Consumer USD/USDC now included in trading_balance when ALLOW_CONSUMER_USD=true
- Updated balance calculation to respect the flag (was hardcoded to ignore it)  
- Improved error messages to show flag status
- Trading balance now: Advanced Trade + Consumer (when flag enabled)

With ALLOW_CONSUMER_USD=true (current setting):
- Consumer USD: \$5.03 → INCLUDED
- Consumer USDC: \$25.41 → INCLUDED  
- Total trading balance: \$30.44

Bot will now start trading immediately on redeploy!"

git push origin main
