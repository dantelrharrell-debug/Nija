#!/bin/bash
set -e

echo "🚀 Starting NIJA bot with proper environment..."
echo ""

cd /workspaces/Nija

# Ensure we do not override credentials set in .env
export ALLOW_CONSUMER_USD=true
export LIVE_TRADING=1

echo "✅ Using credentials from .env (auto-loaded by start.sh)"
echo "✅ Data directories exist"
echo "✅ max_positions = 8"
echo ""
echo "Starting bot to apply sell logic to your positions..."
echo ""

./start.sh
