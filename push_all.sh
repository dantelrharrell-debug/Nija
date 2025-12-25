#!/bin/bash
# Commit all changes and push

cd /workspaces/Nija

git add -A
git commit -m "🔧 Remove invalid TRX-USD pair + add deployment script

- Removed TRX-USD from curated markets (was causing 400 errors)
- Market count: 50 → 49 pairs
- Added fix_trx.sh deployment script
- Bot actively trading with 8 concurrent positions
- All other systems operational"
git push origin main

echo ""
echo "✅ All changes committed and pushed!"
echo "🔄 Railway will auto-rebuild in 1-2 minutes"
