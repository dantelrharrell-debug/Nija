#!/bin/bash

# ---------------------------------------
# Nija Bot Preflight Check Script
# ---------------------------------------

SERVICE_URL="https://nija.onrender.com"
RENDER_SERVICE_ID="your-service-id"  # Replace with your Render service ID
CHECK_TEST_TRADE=true                 # Set to false if you don't want to test trade endpoint

echo "🚀 Starting Nija Preflight Check..."
echo "Service URL: $SERVICE_URL"
echo "---------------------------------------"

# 1) Health endpoint check
echo "🔹 Checking health endpoint..."
HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$SERVICE_URL/health")
if [ "$HTTP_STATUS" -eq 200 ]; then
    echo "✅ Health endpoint OK (HTTP $HTTP_STATUS)"
else
    echo "❌ Health endpoint FAILED (HTTP $HTTP_STATUS)"
fi
echo "---------------------------------------"

# 2) Root endpoint check
echo "🔹 Checking root endpoint..."
ROOT_RESPONSE=$(curl -s "$SERVICE_URL/")
echo "📄 Root response: $ROOT_RESPONSE"
echo "---------------------------------------"

# 3) Stream logs for preflight/JWT confirmation
echo "🔹 Checking preflight & JWT logs..."
echo "⏱ Streaming last 50 log lines..."
render logs "$RENDER_SERVICE_ID" --limit 50 | grep -E "NIJA-PREFLIGHT|NIJA-JWT"

# 4) Optional: test trade endpoint
if [ "$CHECK_TEST_TRADE" = true ]; then
    echo "---------------------------------------"
    echo "🔹 Testing dummy trade endpoint..."
    TRADE_RESPONSE=$(curl -s -X POST "$SERVICE_URL/test_trade" \
        -H "Content-Type: application/json" \
        -d '{"symbol":"BTC-USD","side":"buy","size":0.01}')
    echo "📄 Trade endpoint response: $TRADE_RESPONSE"
fi

echo "---------------------------------------"
echo "✅ Preflight check complete."
echo "If health endpoint is 200, preflight logs show 'Fully live', and test_trade responds, Nija is ready for live trading."
