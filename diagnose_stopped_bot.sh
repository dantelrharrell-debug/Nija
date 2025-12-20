#!/bin/bash
# Comprehensive diagnostic - why did the bot stop?

echo "========================================"
echo "🔍 BOT DIAGNOSTIC"
echo "========================================"
echo ""

echo "1. Checking balance..."
python3 quick_status.py

echo ""
echo "2. Checking if still below $50 minimum..."
echo "   (Bot stops trading if balance < $50)"

echo ""
echo "3. Next steps:"
echo "   a) If balance < $50: Sell remaining crypto or deposit funds"
echo "   b) Check Railway logs for errors"
echo "   c) Verify deployment completed"

echo ""
echo "========================================"
