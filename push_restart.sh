#!/bin/bash
# Push portfolio breakdown balance fix to Railway for redeploy

set -e

echo "📦 Committing balance detection fix..."
git add -A
git commit -m "Fix: prefer portfolio breakdown API for balance detection

- Use get_portfolio_breakdown() to fetch trading balance (more reliable)
- Fall back to get_accounts() if portfolio breakdown unavailable  
- Unblock trading when balance detection returns \$0
- Keep consumer wallet diagnostics in fallback path

Fixes trades stopping due to \$0 balance detection" || echo "No changes to commit"

echo ""
echo "🚀 Pushing to main (triggers Railway redeploy)..."
git push origin main

echo ""
echo "✅ Push complete!"
echo ""
echo "Next steps:"
echo "  1. Check Railway logs: railway logs -f"
echo "  2. Wait 30-60 seconds for redeploy"
echo "  3. Bot should restart and resume trading"
echo ""
echo "Monitor trades:"
echo "  tail -f nija.log | grep -E 'SIGNAL|Trade|balance'"
