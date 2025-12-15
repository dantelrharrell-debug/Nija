#!/bin/bash
set -e

cd /workspaces/Nija

echo "═══════════════════════════════════════════════════════════════════"
echo "  NIJA - Remove PEM Auth & Push Changes"
echo "═══════════════════════════════════════════════════════════════════"
echo ""

# Step 1: Cleanup old PEM documentation
echo "🗑️  Step 1: Removing PEM-related documentation..."
rm -f COINBASE_CONNECTION_FIX.md 2>/dev/null || true
rm -f scripts/test_coinbase_connection.py 2>/dev/null || true
rm -f test_connection.sh 2>/dev/null || true
rm -f commit_coinbase_fix.sh 2>/dev/null || true
rm -f quick_commit.sh 2>/dev/null || true
echo "   ✅ Cleanup complete"
echo ""

# Step 2: Stage all changes
echo "📦 Step 2: Staging all changes..."
git add -A
echo "   ✅ Staged"
echo ""

# Step 3: Commit
echo "📝 Step 3: Committing..."
git commit -m "Remove PEM auth, simplify to JWT-only for Advanced Trade

CRITICAL FIX - Removed ALL PEM/CDP references:
- Stripped PEM file handling from broker_manager.py
- Removed base64, tempfile, cryptography imports
- Simplified connection to JWT-only (AUTH_MODE=JWT)
- Using /v3/accounts endpoint for balance checks
- Cleaned up error messages and validation
- Simplified print_accounts.py test script

Advanced Trade API endpoints:
- GET /v3/accounts
- GET /v3/brokerage/products
- GET /v3/brokerage/products/{product_id}/candles
- POST /v3/brokerage/orders

Authentication: JWT-only
Required: COINBASE_API_KEY, COINBASE_API_SECRET
No PEM files needed" 2>/dev/null || echo "   ℹ️  Nothing new to commit"
echo ""

# Step 4: Push
echo "🚀 Step 4: Pushing to origin main..."
git push origin main
echo ""

# Step 5: Summary
echo "═══════════════════════════════════════════════════════════════════"
echo "  ✅ ALL CHANGES PUSHED SUCCESSFULLY"
echo "═══════════════════════════════════════════════════════════════════"
echo ""
echo "Changes:"
echo "  • Removed ALL PEM/CDP/cryptography code"
echo "  • Simplified to JWT-only authentication"
echo "  • Using /v3/accounts for balance fetching"
echo "  • Cleaned up documentation"
echo ""
echo "Test your connection:"
echo "  python scripts/print_accounts.py"
echo ""
echo "Required env vars:"
echo "  • COINBASE_API_KEY"
echo "  • COINBASE_API_SECRET"
echo ""
