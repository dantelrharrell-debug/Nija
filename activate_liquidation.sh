#!/bin/bash
cd /workspaces/Nija
git add LIQUIDATE_ALL_NOW.conf bot/trading_strategy.py check_liquidation_status.py
git commit -m "EMERGENCY: Activate hardened liquidation with timeout protection and guaranteed cleanup"
git push origin main
echo "✅ Push complete - Railway redeploy triggered"
