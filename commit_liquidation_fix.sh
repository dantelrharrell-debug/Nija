#!/bin/bash

# Commit the liquidation error handling fix
cd /workspaces/Nija

echo "📦 Adding changes..."
git add bot/trading_strategy.py

echo "💾 Committing fix..."
git commit -m "Add comprehensive error handling to liquidation loop to prevent bot crash

- Wrap entire close_excess_positions() in try-catch to handle API failures gracefully
- Skip positions with fetch/order failures instead of crashing
- Track successfully closed position count
- Add detailed logging of liquidation progress
- Enhance startup overage logging with full stack traces
- Bot now continues even if liquidation partially fails"

echo "🚀 Pushing to Railway..."
git push origin main

echo "✅ Commit complete. Railway will auto-redeploy with fix."
