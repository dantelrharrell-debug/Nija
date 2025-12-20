#!/bin/bash
set -e

echo "🔧 Creating required data directory..."
mkdir -p /usr/src/app/data
mkdir -p /workspaces/Nija/data

echo "✅ Data directories created"
echo ""
echo "🚀 Starting NIJA with proper environment..."
echo ""

# Set environment variables from .env
export $(grep -v '^#' .env | xargs)
export ALLOW_CONSUMER_USD=true
export LIVE_TRADING=1

# Start the bot
exec ./start.sh
