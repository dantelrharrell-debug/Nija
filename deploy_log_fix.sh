#!/bin/bash
# Deploy log message fix

cd /workspaces/Nija
git add bot.py
git commit -m "🚀 Fix log message: 15s cadence not 30s - 15-DAY GOAL MODE"
git push origin main

echo ""
echo "✅ Deployment complete! Railway will restart in ~1 minute."
echo "Watch for updated log: '🚀 Starting ULTRA AGGRESSIVE trading loop (15s cadence - 15-DAY GOAL MODE)...'"
