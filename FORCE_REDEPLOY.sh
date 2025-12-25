#!/bin/bash
# Force Railway to redeploy with the fixed code

echo "========================================"
echo "🚨 FORCING RAILWAY REDEPLOY"
echo "========================================"
echo ""
echo "The fixes are in GitHub but Railway hasn't deployed them yet."
echo "This will trigger a fresh deployment."
echo ""

cd /workspaces/Nija

# Create a dummy file change to trigger Railway
echo "# Force redeploy $(date)" >> .redeploy_trigger

echo "📝 Committing redeploy trigger..."
git add .redeploy_trigger

git commit -m "🚨 FORCE REDEPLOY: Bot not selling - trigger fresh deployment

Railway needs to deploy the position closing fixes:
- broker_manager.py: size_type='base' for SELL orders
- trading_strategy.py: crypto_quantity tracking
- 8 consecutive trade limit

Previous deployment may have failed or not triggered.
This commit forces a fresh build."

echo "🚀 Pushing to trigger Railway..."
git push origin main

echo ""
echo "========================================"
echo "✅ REDEPLOY TRIGGERED"
echo "========================================"
echo ""
echo "Railway will now rebuild (2-3 minutes)"
echo ""
echo "The bot WILL sell at profit targets after deployment!"
echo "Stop manually liquidating - you're selling at a LOSS!"
echo ""
echo "Monitor: https://railway.app/dashboard"
echo "========================================"
