#!/bin/bash
set -e

echo "📝 Committing graceful shutdown handlers..."

git add bot.py start.sh

git commit -m "Add graceful SIGTERM/SIGINT handlers to prevent Railway restart loops

- bot.py: Install signal handlers for SIGTERM/SIGINT to exit cleanly
- start.sh: Treat exit code 143 (SIGTERM) as graceful shutdown, not crash
- Prevents Railway from restarting bot when platform stops container
- Ensures liquidation cycles can complete without being killed mid-execution"

echo "🚀 Pushing to main..."
git push origin main

echo "✅ Changes committed and pushed!"
echo ""
echo "Next: Railway will auto-deploy. Watch logs for:"
echo "  - 'Received signal ..., shutting down gracefully' on SIGTERM"
echo "  - Liquidation completing to 7 positions without mid-cycle stops"
