#!/bin/bash
set -e

cd /workspaces/Nija

# Add the specific files
git add bot/trading_strategy.py RENDER_GUIDE.md deploy_fix.sh RENDER_SETUP.md clear_commits.sh

# Commit
git -c commit.gpgsign=false commit -m "Fix: Enforce \$5 minimum position size + Add Render deployment

- Enforce Coinbase \$5 minimum in trading_strategy.py line 500
- Fixes positions showing \$1.12 instead of \$5.00
- Add RENDER_SETUP.md complete deployment guide
- Add RENDER_GUIDE.md quick reference
- Add deployment scripts"

# Push
git push origin main

echo ""
echo "✅ Changes deployed to GitHub"
echo "🚀 Ready for Render deployment - See RENDER_SETUP.md"
echo ""
