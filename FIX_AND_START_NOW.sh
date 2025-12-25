#!/bin/bash
set -e

echo "=========================================="
echo "NIJA BOT - EMERGENCY FIX & RESTART"
echo "=========================================="
echo ""

# Kill any running bot processes
echo "1️⃣ Stopping any running bot processes..."
pkill -f "python.*bot.py" || true
pkill -f "bot.py" || true
sleep 2

# Verify .env exists
if [ ! -f .env ]; then
    echo "❌ ERROR: .env file not found!"
    echo "   Create .env with your Coinbase credentials"
    exit 1
fi

echo "✅ .env file found"
echo ""

# Load .env
echo "2️⃣ Loading credentials from .env..."
set -a
source .env
set +a

# Verify credentials are set
if [ -z "$COINBASE_API_KEY" ]; then
    echo "❌ ERROR: COINBASE_API_KEY not set in .env"
    exit 1
fi

if [ -z "$COINBASE_API_SECRET" ]; then
    echo "❌ ERROR: COINBASE_API_SECRET not set in .env"
    exit 1
fi

echo "✅ Credentials loaded"
echo "   API Key: ${COINBASE_API_KEY:0:50}..."
echo "   API Secret: ${COINBASE_API_SECRET:0:30}..."
echo ""

# Test connection BEFORE starting bot
echo "3️⃣ Testing Coinbase API connection..."
python -u VERIFY_API_CONNECTION.py

# Check if test passed
if [ $? -eq 0 ]; then
    echo ""
    echo "✅ Connection test PASSED"
    echo ""
else
    echo ""
    echo "❌ Connection test FAILED"
    echo "   Fix credentials before starting bot"
    exit 1
fi

# Force live mode
export PAPER_MODE=false
export ALLOW_CONSUMER_USD=true

echo "4️⃣ Starting NIJA bot in LIVE MODE..."
echo "   PAPER_MODE=${PAPER_MODE}"
echo "   ALLOW_CONSUMER_USD=${ALLOW_CONSUMER_USD}"
echo ""

# Start bot
if [ -x ./.venv/bin/python ]; then
    ./.venv/bin/python -u bot.py 2>&1 | tee -a nija.log
else
    python3 -u bot.py 2>&1 | tee -a nija.log
fi
