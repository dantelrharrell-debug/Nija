#!/bin/bash
# NIJA Bot Restart Script

echo "🔄 Stopping existing NIJA processes..."
pkill -f live_trading.py
sleep 2

echo "🚀 Starting NIJA with updated code..."
cd /workspaces/Nija/bot
nohup python live_trading.py > /workspaces/Nija/nija.log 2>&1 &

echo "✅ NIJA restarted! Check logs with: tail -f /workspaces/Nija/nija.log"
echo "💰 New features active:"
echo "   - Minimum trade: \$0.01"
echo "   - Position sizing: 2-10% of account"
echo "   - Dual RSI strategy (momentum + pullback)"
echo "   - Enhanced trailing system"
