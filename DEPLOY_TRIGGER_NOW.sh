#!/bin/bash
echo "🚀 TRIGGERING RENDER DEPLOYMENT..."

git add .render-trigger
git commit -m "FORCE DEPLOY: Trigger Render to deploy dual API balance fix

Balance detection fix is on GitHub (commit b9c37c76) but not deployed.
This commit forces Render auto-deploy to pull the latest code.

Expected result: Balance shows $30.64, trades execute successfully"

git push origin main

echo ""
echo "✅ PUSHED! Render should start deploying in ~30 seconds"
echo ""
echo "Watch for in logs:"
echo "  - Deploy live!"
echo "  - 💰 Checking v2 API (Consumer wallets)..."
echo "  - 💰 Checking v3 API (Advanced Trade)..."
echo "  - TRADING BALANCE: $30.XX"
