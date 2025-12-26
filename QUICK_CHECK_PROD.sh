#!/bin/bash
# Quick check: Are the broker fixes in production?

echo "Checking if broker fix (quantity + size_type) is in production..."
echo ""

# Try to get the remote file
git show origin/main:bot/trading_strategy.py 2>/dev/null | grep -A5 "place_market_order" | grep -E "(quantity|size_type)" | head -3

if [ $? -eq 0 ]; then
    echo ""
    echo "✅ BROKER FIX IS IN PRODUCTION!"
    echo ""
    echo "Expected next: Bot liquidates all 13 positions on next cycle"
else
    echo ""
    echo "❌ Broker fix NOT found in production"
    echo ""
    echo "This means the earlier push didn't include the broker method fixes"
    echo "Need to: git push origin main"
fi
