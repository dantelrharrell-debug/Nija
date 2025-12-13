#!/bin/bash
cd /workspaces/Nija

echo "📝 Staging portfolio scanner and broker updates..."
git add find_usd_portfolio.py bot/broker_manager.py

echo "✍️  Committing..."
git commit -m "Auto-detect correct Coinbase portfolio for USD balance

- Add portfolio scanner script (find_usd_portfolio.py) for diagnostics
- Update get_account_balance() to scan all portfolios via get_portfolios()
- Auto-detect portfolio containing USD and query with retail_portfolio_id
- Fixes \$0.00 balance issue when USD is in non-default portfolio
- Maintains fallback to default accounts if portfolio scan fails"

echo "🚀 Pushing to origin/main..."
git push origin main

echo "✅ Done!"
git log --oneline -1
