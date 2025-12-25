#!/bin/bash
# Resume normal trading by removing emergency stop

echo "🔓 Resuming NIJA trading..."

if [ -f "TRADING_EMERGENCY_STOP.conf" ]; then
    rm TRADING_EMERGENCY_STOP.conf
    echo "✅ Emergency stop removed"
else
    echo "ℹ️  Emergency stop already removed"
fi

echo ""
echo "📊 Current status:"
ls -la TRADING_*.conf 2>/dev/null || echo "No trading control files active"

echo ""
echo "🚀 Committing change and deploying..."
git add -A
git commit -m "Remove emergency stop - resume normal trading with v7.2 profitability upgrades"
git push

echo ""
echo "✅ DONE - Railway will auto-redeploy in ~30 seconds"
echo "🔄 Trading will resume on next cycle (every 2.5 minutes)"
