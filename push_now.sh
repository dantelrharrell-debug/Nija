#!/bin/bash
set -e

cd /workspaces/Nija

echo "🧹 Cleaning up..."
git add -A

echo ""
echo "📝 Committing changes..."
git commit -m "Remove PEM auth, simplify to JWT-only for Advanced Trade

CRITICAL FIX:
- Removed ALL PEM/CDP/cryptography references
- Simplified to JWT-only authentication (AUTH_MODE=JWT, USE_CDP_AUTH=False)
- Removed base64, tempfile, PEM file handling
- Using /v3/accounts endpoint for balance checks
- Cleaned up broker_manager.py connection logic
- Simplified print_accounts.py test script

Advanced Trade API uses:
- GET /v3/accounts
- GET /v3/brokerage/products
- GET /v3/brokerage/products/{product_id}/candles
- POST /v3/brokerage/orders

Authentication: JWT-only (no PEM files needed)
Required env vars: COINBASE_API_KEY, COINBASE_API_SECRET" || echo "✅ Nothing to commit"

echo ""
echo "🚀 Pushing to origin..."
git push origin main

echo ""
echo "✅ DONE! All changes pushed."
echo ""
echo "Test connection:"
echo "  python scripts/print_accounts.py"
