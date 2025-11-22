#!/bin/bash
# =============================
# start_all.sh - Nija Trading Bot
# FULL LIVE MODE CONFIRMATION
# =============================

echo "=============================="
echo "🔹 Starting Container"
echo "=============================="

# --- Load environment variables from .env if present ---
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi

# --- Check LIVE mode ---
if [ "$LIVE_TRADING" = "1" ]; then
    echo "⚡ LIVE TRADING MODE ENABLED! Trades WILL execute."
    MODE="LIVE"
else
    echo "⚠️  LIVE TRADING NOT ENABLED. Running in SAFE/DRY mode."
    MODE="TEST"
fi

# --- Check TradingView Webhook Secret ---
if [ -z "$TRADINGVIEW_WEBHOOK_SECRET" ]; then
    echo "❌ WARNING: TRADINGVIEW_WEBHOOK_SECRET not set! Webhooks NOT secure."
else
    echo "✅ TradingView webhook secret detected (masked): ${TRADINGVIEW_WEBHOOK_SECRET:0:4}****"
fi

# --- Print deployment summary ---
echo ""
echo "===== DEPLOYMENT SUMMARY ====="
echo "Mode: $MODE"
echo "API Key: ${COINBASE_API_KEY:0:4}****"
echo "API Secret: **** (hidden)"
echo "PEM: **** (hidden)"
echo "Org ID: ${COINBASE_ORG_ID:0:4}****"
echo "=============================="
echo ""

# --- Optional: test Coinbase connection ---
echo "🔹 Verifying Coinbase connection..."
python3 - <<'EOF'
import os
import logging
from nija_client import CoinbaseClient

logging.basicConfig(level=logging.INFO)

try:
    client = CoinbaseClient()
    accounts = client.fetch_accounts()  # fetch account balances
    logging.info(f"✅ Coinbase connection verified. Accounts fetched:")
    for acc in accounts:
        logging.info(f"  - {acc['currency']}: {acc['balance']} available")
except Exception as e:
    logging.error(f"❌ Coinbase connection failed: {e}")
    exit(1)
EOF

echo ""
echo "🚀 Starting Nija trading bot..."
exec gunicorn main:app -b 0.0.0.0:5000 --workers 1 --worker-class sync
