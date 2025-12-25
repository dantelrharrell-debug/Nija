#!/bin/bash
# Deploy the position closing fix to Railway

echo "=================================="
echo "🚀 DEPLOYING POSITION CLOSING FIX"
echo "=================================="
echo ""
echo "This will:"
echo "  1. Commit changes to git"
echo "  2. Push to GitHub"
echo "  3. Railway will auto-deploy (2-3 minutes)"
echo "  4. Bot will start selling positions for profit!"
echo ""

cd /workspaces/Nija

echo "📝 Adding files..."
git add bot/trading_strategy.py bot/broker_manager.py

echo "💾 Committing..."
git commit -m "🔧 CRITICAL FIX: Bot now sells positions for profit

PROBLEM: Bot buying but not selling (46 buys vs 4 sells)

FIXES:
- Store actual crypto_quantity when opening positions
- Use stored quantity (not recalculated) when closing
- Pass size_type='base' for SELL orders to specify crypto amount
- Extract filled_size from Coinbase responses

Files changed:
- bot/trading_strategy.py (3 edits)
- bot/broker_manager.py (3 edits)

Impact: Positions will now close automatically at profit targets!"

echo "🚀 Pushing to GitHub..."
git push origin main

echo ""
echo "=================================="
echo "✅ DEPLOYED!"
echo "=================================="
echo ""
echo "Railway will rebuild in 2-3 minutes."
echo "After deployment, bot will:"
echo "  - Buy crypto when signals appear"
echo "  - SELL automatically at profit targets"
echo "  - Recycle capital continuously"
echo ""
echo "Monitor at: https://railway.app/dashboard"
echo "=================================="
