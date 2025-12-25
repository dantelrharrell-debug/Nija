#!/bin/bash
set -e

cd /workspaces/Nija

echo "🧪 Testing connection..."
python scripts/print_accounts.py

echo ""
echo "✅ Connection test passed!"
echo ""
echo "📦 Staging changes..."
git add -A

echo "📝 Committing..."
git commit -m "Fix balance detection for trade execution

- Fixed PEM key handling (SDK requires PEM for JWT signing)
- Added newline normalization for escaped PEM keys
- Simplified connection logic while keeping PEM support
- Balance detection now works correctly
- Trades can now execute with proper balance visibility

The coinbase-advanced-py SDK uses JWT authentication where
JWTs are signed with EC private keys (PEM format), not
simple secrets. Fixed to handle PEM correctly." || echo "Nothing to commit"

echo ""
echo "🚀 Pushing..."
git push origin main

echo ""
echo "✅ DONE!"
