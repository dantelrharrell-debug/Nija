#!/bin/bash
cd /workspaces/Nija
git add -A
git commit -m "CRITICAL FIX: Properly detect Advanced Trade balance

User has \$30.64 in Advanced Trade but bot only detected \$25.81 from Consumer API.
Fixed broker_manager.py to check BOTH v2 + v3 APIs and properly sum balances.

Changes:
- broker_manager.py: Added v2 API check for Consumer wallets
- broker_manager.py: Enhanced v3 API check for Advanced Trade
- broker_manager.py: Sum both sources for accurate total
- Added diagnostic tools for troubleshooting

This should immediately fix INSUFFICIENT_FUND errors on Render."
git push origin main
echo ""
echo "✅ PUSHED! Render will deploy in ~2 minutes"
echo "   Watch at: https://dashboard.render.com"
