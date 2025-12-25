#!/usr/bin/env bash
set -e

echo ""
echo "=========================================="
echo "🛑 EMERGENCY SHUTDOWN - STOPPING BOT"
echo "=========================================="
echo ""

# Create emergency stop file
echo "1️⃣ Creating EMERGENCY_STOP.conf..."
touch /workspaces/Nija/EMERGENCY_STOP.conf
touch /workspaces/Nija/FORCE_EXIT_ALL.conf
touch /workspaces/Nija/TRADING_EMERGENCY_STOP.conf

echo "✅ Emergency stop files created"
echo ""

# Kill any running bot processes
echo "2️⃣ Killing bot processes..."
pkill -f "python.*bot" || echo "No bot processes found"
pkill -f "nija" || echo "No nija processes found"

echo "✅ Bot processes stopped"
echo ""

# Force liquidate all positions
echo "3️⃣ Liquidating ALL crypto positions..."
python3 /workspaces/Nija/FORCE_SELL_ALL_NOW.py

echo ""
echo "=========================================="
echo "✅ EMERGENCY SHUTDOWN COMPLETE"
echo "=========================================="
echo ""
echo "The bot is now STOPPED and all positions"
echo "have been liquidated to USD."
echo ""
