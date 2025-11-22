#!/bin/bash
set -e  # Exit immediately if a command fails

# --- Load environment variables ---
echo "🔹 Checking environment variables..."
: "${COINBASE_API_KEY:?Need to set COINBASE_API_KEY}"
: "${COINBASE_API_SECRET:?Need to set COINBASE_API_SECRET}"
: "${COINBASE_PEM_CONTENT:?Need to set COINBASE_PEM_CONTENT}"
: "${COINBASE_ORG_ID:?Need to set COINBASE_ORG_ID}"

# --- Live trading flag ---
LIVE_MODE=${LIVE_TRADING:-0}

if [ "$LIVE_MODE" -eq 1 ]; then
    echo "⚠️  LIVE TRADING MODE ENABLED!"
else
    echo "ℹ️  Running in SIMULATION mode."
fi

# --- Print a summary (mask sensitive info) ---
echo ""
echo "===== Deployment Summary ====="
echo "Mode: $([ "$LIVE_MODE" -eq 1 ] && echo LIVE || echo SIMULATION)"
echo "API Key: ${COINBASE_API_KEY:0:4}****"
echo "API Secret: **** (hidden)"
echo "PEM: **** (hidden)"
echo "Org ID: ${COINBASE_ORG_ID:0:4}****"
echo "=============================="
echo ""

# --- Confirmation if LIVE ---
if [ "$LIVE_MODE" -eq 1 ]; then
    read -p "Confirm you want to START LIVE TRADING? Type YES to proceed: " CONFIRM
    if [ "$CONFIRM" != "YES" ]; then
        echo "❌ Live trading cancelled by user."
        exit 1
    fi
fi

# --- Start bot ---
echo "🚀 Starting Nija trading bot..."
exec gunicorn -b 0.0.0.0:5000 main:app --workers 1 --log-level info
