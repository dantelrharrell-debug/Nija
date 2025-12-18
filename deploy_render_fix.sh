#!/bin/bash
# Quick deploy to Render with balance fix

echo "🚀 Deploying URGENT FIX to Render..."
echo ""
echo "Changes:"
echo "  ✅ Removed Consumer account filtering"
echo "  ✅ Now counting ALL USD/USDC balances"
echo "  ✅ Enhanced logging to show all accounts"
echo ""

git add bot/broker_manager.py
git add render.yaml
git add deploy_render_fix.sh

git commit -m "URGENT: Remove Consumer account filtering - count ALL balances

The previous filtering was too aggressive and was incorrectly
skipping funded accounts. Now counting ALL USD/USDC regardless
of account type (wallet, consumer, advanced trade, etc).

Enhanced logging to show exactly what accounts are detected
and their balances for better diagnostics.

This should immediately fix INSUFFICIENT_FUND errors on Render."

echo ""
echo "✅ Committed changes"
echo "📤 Pushing to GitHub..."
echo ""

git push origin main

echo ""
echo "🎯 PUSHED TO GITHUB!"
echo ""
echo "Render will auto-deploy in ~2 minutes"
echo ""
echo "Watch deployment at:"
echo "https://dashboard.render.com"
echo ""
echo "After deploy, check logs for lines like:"
echo "  ✅ USD: $XX.XX (type=wallet)"
echo "  ✅ USDC: $XX.XX (type=ACCOUNT_TYPE_CRYPTO)"
echo ""
echo "Bot should start trading within 5 minutes!"
