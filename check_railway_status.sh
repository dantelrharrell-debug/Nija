#!/bin/bash
echo "========================================="
echo "  CHECKING NIJA DEPLOYMENT STATUS"
echo "========================================="
echo ""
echo "To check if NIJA is running on Railway:"
echo "1. Go to: https://railway.app/dashboard"
echo "2. Find your NIJA project"
echo "3. Check the deployment status"
echo ""
echo "To STOP the bot from auto-buying:"
echo "  • Click on the project"
echo "  • Go to Settings"
echo "  • Click 'Pause Deployment' or 'Delete Service'"
echo ""
echo "========================================="
echo ""
echo "Current environment check:"
if [ -f .env ]; then
    echo "✅ .env file found"
    if grep -q "COINBASE_API_KEY" .env; then
        echo "✅ API credentials configured"
    fi
else
    echo "❌ No .env file found"
fi
echo ""
echo "To verify bot is stopped, wait 2-3 minutes after pausing,"
echo "then sell a small amount and see if it gets bought back."
