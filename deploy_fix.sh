#!/bin/bash
set -e

echo "🚀 Deploying $5 minimum position size fix..."

cd /workspaces/Nija

# Stage changes
git add bot/trading_strategy.py

# Commit with clear message
git commit -m "Fix: Enforce $5 minimum position size for Coinbase trades

- Add max(5.00, calculated_size) in trading_strategy.py
- Ensures all positions meet Coinbase Advanced Trade $5 minimum
- Fixes trades failing with $1.12 position sizes
- With $55.81 balance: positions will be $5.00 instead of $1.12"

# Push to GitHub
git push origin main

echo ""
echo "✅ Fix deployed to GitHub"
echo "📦 Latest commit available for Railway/Render deployment"
echo ""
echo "Next steps:"
echo "1. Railway will auto-deploy if connected to GitHub"
echo "2. Or deploy to Render.com for guaranteed fresh build"
echo ""
