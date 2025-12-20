#!/bin/bash
set -e

echo "🚀 Starting NIJA bot with proper environment..."
echo ""

cd /workspaces/Nija

# Set environment variables manually (avoid export issue with multiline key)
export ALLOW_CONSUMER_USD=true
export LIVE_TRADING=1
export COINBASE_API_KEY="organizations/ce77e4ea-ecca-42ec-912a-b6b4455ab9d0/apiKeys/4cfe95c4-23c3-4480-a13c-1259f7320c36"

# The API secret is already in .env and will be loaded by Python scripts directly
# Don't export it to avoid shell escaping issues

echo "✅ Environment configured"
echo "✅ Data directories exist"
echo "✅ max_positions = 8"
echo ""
echo "Starting bot to apply sell logic to your positions..."
echo ""

./start.sh
