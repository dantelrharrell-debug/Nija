#!/bin/bash
# Investigation wrapper that loads environment variables

echo "🔍 Loading environment variables..."
if [ -f .env ]; then
    set -a
    source .env
    set +a
    echo "✅ Environment loaded from .env"
else
    echo "❌ .env file not found!"
    exit 1
fi

echo ""
echo "===================================================================================="
echo "STEP 1: CHECK TRANSACTION HISTORY (Where did the money go?)"
echo "===================================================================================="
echo ""

python3 check_transaction_history.py

echo ""
echo ""
echo "===================================================================================="
echo "STEP 2: ANALYZE PAST TRADES (Profitability analysis)"
echo "===================================================================================="
echo ""

python3 analyze_past_trades.py

echo ""
echo "===================================================================================="
echo "✅ INVESTIGATION COMPLETE"
echo "===================================================================================="
