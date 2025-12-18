#!/bin/bash
echo "🚀 FORCING RENDER REDEPLOY..."
echo ""
echo "The fix is on GitHub but Render hasn't deployed it."
echo "Creating a dummy commit to trigger Render's auto-deploy..."
echo ""

# Create a timestamp file to force a new commit
echo "Last deployment: $(date)" > .render-deploy-timestamp

git add .render-deploy-timestamp
git commit -m "🚀 FORCE REDEPLOY: Trigger Render to pull broker_manager.py fix

The broker_manager.py fix (commit b9c37c76) is on GitHub but Render
hasn't deployed it yet. Current Render logs still show:
- Balance: \$25.81 (should be \$30.64)
- INSUFFICIENT_FUND errors

This dummy commit forces Render to redeploy and pull the fix.

Expected after deployment:
- Logs will show: 'Checking v2 API (Consumer wallets)...'
- Logs will show: 'Checking v3 API (Advanced Trade)...'
- Balance will show: '\$30.XX'
- Trades will execute successfully"

echo ""
echo "📤 Pushing to GitHub to trigger Render..."
git push origin main

echo ""
echo "==============================================="
echo "✅ FORCE REDEPLOY TRIGGERED!"
echo "==============================================="
echo ""
echo "Render will now:"
echo "  1. Detect new commit on GitHub"
echo "  2. Pull latest code (includes broker_manager.py fix)"
echo "  3. Rebuild Docker image"
echo "  4. Deploy and restart bot"
echo ""
echo "Expected timeline:"
echo "  T+0:00 - Deployment starts (NOW)"
echo "  T+2:00 - Build completes"
echo "  T+2:30 - Bot restarts with new code"
echo "  T+3:00 - Balance shows \$30.XX in logs"
echo "  T+5:00 - First successful trade"
echo ""
echo "Watch logs at: https://dashboard.render.com"
echo ""
echo "Look for these NEW log lines:"
echo "  💰 Checking v2 API (Consumer wallets)..."
echo "  💰 Checking v3 API (Advanced Trade)..."
echo "  💰 TOTAL BALANCE: \$30.XX"
echo "  ✅ Sufficient funds in Advanced Trade for trading!"
echo ""
