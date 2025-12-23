#!/bin/bash
# Update Railway environment variables for position cap configuration
# Run this after testing locally to deploy to production

echo "🚀 Updating Railway environment variables..."
echo ""
echo "Run these commands in your Railway dashboard or CLI:"
echo ""
echo "railway variables set MAX_CONCURRENT_POSITIONS=7"
echo "railway variables set REENTRY_COOLDOWN_MINUTES=120"
echo "railway variables set MIN_CASH_TO_BUY=5.0"
echo "railway variables set MINIMUM_TRADING_BALANCE=25.0"
echo ""
echo "Then redeploy:"
echo "railway up --detach"
echo ""
echo "Or if using Railway dashboard:"
echo "1. Go to your project → Variables"
echo "2. Add the variables above"
echo "3. Click 'Deploy' to restart with new config"
