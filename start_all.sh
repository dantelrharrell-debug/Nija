#!/bin/bash
set -e  # Exit immediately if a command fails

# --- Load environment variables ---
: "${COINBASE_API_KEY:?Need to set COINBASE_API_KEY}"
: "${COINBASE_API_SECRET:?Need to set COINBASE_API_SECRET}"
: "${COINBASE_PEM_CONTENT:?Need to set COINBASE_PEM_CONTENT}"
: "${COINBASE_ORG_ID:?Need to set COINBASE_ORG_ID}"

# --- Enforce live mode ---
LIVE_MODE=1
echo "⚡ LIVE TRADING MODE ENABLED! Trades WILL execute."

# --- Print a masked summary ---
echo ""
echo "===== LIVE DEPLOYMENT SUMMARY ====="
echo "Mode: LIVE"
echo "API Key: ${COINBASE_API_KEY:0:4}****"
echo "API Secret: **** (hidden)"
echo "PEM: **** (hidden)"
echo "Org ID: ${COINBASE_ORG_ID:0:4}****"
echo "==================================="
echo ""

# --- Immediate start (no confirmation) ---
echo "🚀 Starting Nija trading bot in FULL LIVE mode..."
exec gunicorn -b 0.0.0.0:5000 main:app --workers 1 --log-level info
