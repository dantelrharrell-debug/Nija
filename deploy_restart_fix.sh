#!/bin/bash
# Deploy NIJA restart fix to Railway
# Fixes: 1) Portfolio breakdown API for balance detection
#        2) Lower minimum capital to $10 (was $50)

set -e

echo "╔════════════════════════════════════════════════════════╗"
echo "║     NIJA BOT RESTART - DEPLOYING CRITICAL FIXES        ║"
echo "╚════════════════════════════════════════════════════════╝"
echo ""
echo "Fixes included:"
echo "  1. ✅ Portfolio breakdown API for balance detection"
echo "  2. ✅ Lower minimum capital: $10 (was $50)"
echo "  3. ✅ Updated README status"
echo ""

# Add all changes
git add bot/broker_manager.py bot/trading_strategy.py README.md

# Commit with detailed message
git commit -m "CRITICAL: Fix trading restart

- Use portfolio breakdown API for balance (more reliable than get_accounts)
- Lower minimum capital to \$10 (was \$50) to allow trading with ~\$84 balance
- Update README status to reflect restart in progress

Fixes:
- Balance detection returning \$0 (get_accounts API issue)
- Bot refusing to trade due to \$50 minimum (balance is ~\$84)

Bot should resume trading immediately after deployment." || echo "No changes to commit"

# Push to Railway
echo ""
echo "🚀 Pushing to Railway..."
git push origin main

echo ""
echo "✅ DEPLOYMENT COMPLETE"
echo ""
echo "Railway will auto-redeploy in ~30-60 seconds"
echo ""
echo "Monitor progress:"
echo "  tail -f trade_journal.jsonl"
echo "  python3 check_bot_status.py"
echo ""
