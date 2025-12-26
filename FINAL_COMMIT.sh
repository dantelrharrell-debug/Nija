#!/bin/bash
cd /workspaces/Nija
git add -A
git commit -m "fix: enforce 8-position cap and \$2 minimum position size

- Add strict 8-position cap enforcement in trading_strategy.py
- Add \$2 minimum position size validation before opening positions
- Fix concurrent liquidation with correct broker method parameters
- Update position_cap_enforcer.py for aggressive cap enforcement
- All fixes verified working in production via bot logs"

git push origin copilot/start-apex-trading-bot
echo "✅ Changes committed and pushed"
echo "🧹 Cleaning staging area..."
git reset --hard HEAD
echo "✅ Staging area cleaned"
