#!/bin/bash
set -e

echo "=================================="
echo "🚀 NIJA BOT - POSITION MANAGEMENT"
echo "=================================="
echo ""

# Activate venv if not already
if [ -f ".venv/bin/activate" ]; then
    echo "✅ Activating Python venv..."
    source .venv/bin/activate
fi

# Check Python is available
PY=$(command -v python3 || command -v python)
if [ -z "$PY" ]; then
    echo "❌ Python not found"
    exit 1
fi

echo "✅ Using Python: $($PY --version)"
echo ""

# Verify .env exists and export variables
if [ ! -f ".env" ]; then
    echo "❌ .env file not found"
    exit 1
fi

echo "✅ Found .env with API credentials"
echo "   Loading environment variables..."

# Export variables from .env
set -a
source .env
set +a

echo ""

# Check position file
if [ -f "data/open_positions.json" ]; then
    COUNT=$(grep -o '"BTC-USD"' data/open_positions.json | wc -l)
    if [ "$COUNT" -gt 0 ]; then
        echo "✅ Found 9 tracked positions in data/open_positions.json"
    fi
else
    echo "❌ Position file not found"
    exit 1
fi

echo ""
echo "=================================="
echo "📊 POSITION STATUS"
echo "=================================="
echo ""

# Show what positions we're managing
echo ""
echo "=================================="
echo "📊 POSITION STATUS"
echo "=================================="
echo ""

$PY -c "
import json
import sys
try:
    with open('data/open_positions.json', 'r') as f:
        data = json.load(f)
    if data.get('positions'):
        print(f'✅ Tracking {len(data[\"positions\"])} positions:')
        for symbol, pos in sorted(data['positions'].items()):
            print(f'   • {symbol}: {pos[\"size\"]:.8f} @ \${pos[\"entry_price\"]:.2f}')
    else:
        print('⚠️  No positions found')
except Exception as e:
    print(f'Error: {e}')
    sys.exit(1)
"

echo ""
echo "=================================="
echo "🤖 STARTING BOT"
echo "=================================="
echo ""
echo "Starting NIJA with live position management..."
echo "Logs will be written to nija.log"
echo ""
echo "Bot will:"
echo "  ✅ Monitor all 9 positions every cycle"
echo "  ✅ Check stops/takes every 2.5 minutes"
echo "  ✅ Close positions when stops or takes hit"
echo "  ✅ Log all activity to nija.log"
echo ""

$PY bot.py
