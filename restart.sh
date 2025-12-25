#!/bin/bash
# ============================================================
# NIJA BOT RESTART - December 21, 2025
# Restarts bot with balance detection fix
# ============================================================

set -e

echo ""
echo "╔════════════════════════════════════════════════════════╗"
echo "║        NIJA BOT RESTART - BALANCE FIX DEPLOYED         ║"
echo "╚════════════════════════════════════════════════════════╝"
echo ""

# Check if running in Railway or local
if [ -n "$RAILWAY_ENVIRONMENT_NAME" ]; then
    echo "🚂 Railway environment detected"
    echo "   Service will restart automatically when pushed"
    echo ""
    echo "To deploy the balance fix:"
    echo "   git push origin main"
    echo ""
    exit 0
fi

# Local environment - run the bot
echo "💻 Local environment detected"
echo ""

# Check for credentials
if [ -z "$COINBASE_API_KEY" ] || [ -z "$COINBASE_API_SECRET" ]; then
    echo "⚠️  MISSING COINBASE CREDENTIALS"
    echo ""
    echo "Set these environment variables:"
    echo "   export COINBASE_API_KEY='organizations/...'"
    echo "   export COINBASE_API_SECRET='-----BEGIN...'"
    echo ""
    echo "Then run: ./restart.sh"
    exit 1
fi

echo "✅ Coinbase credentials found"
echo ""

# Display startup info
echo "📊 BOT CONFIGURATION:"
echo "   - Strategy: APEX v7.1"
echo "   - Mode: LIVE TRADING (real money)"
echo "   - Markets: 50 top liquidity pairs"
echo "   - Scan interval: 15 seconds"
echo "   - Position size: $5-75 per trade"
echo "   - Max concurrent: 8 positions"
echo ""

# Confirm startup
read -p "🚀 Start NIJA in LIVE mode? (Type 'YES' to confirm): " confirmation

if [ "$confirmation" != "YES" ]; then
    echo "❌ Startup cancelled"
    exit 1
fi

echo ""
echo "🚀 STARTING NIJA TRADING BOT..."
echo "════════════════════════════════════════════════════════"
echo ""

# Set mode and start
export PAPER_MODE=false
cd "$(dirname "$0")"
python3 bot.py

echo ""
echo "Bot stopped."
