#!/bin/bash
# Test script for aggregated reporting endpoints
# This script verifies the new aggregation endpoints are accessible

echo "🧪 Testing NIJA Aggregated Reporting Implementation"
echo "=================================================="
echo ""

# Configuration
HOST="localhost"
PORT="5001"
BASE_URL="http://${HOST}:${PORT}"

echo "📋 Prerequisites:"
echo "  - Dashboard server must be running: python bot/dashboard_server.py"
echo "  - Or user API server: python bot/user_dashboard_api.py"
echo ""

# Check if server is running
echo "🔍 Checking if server is running..."
if curl -s -o /dev/null -w "%{http_code}" "${BASE_URL}/api/health" | grep -q "200"; then
    echo "✅ Server is running at ${BASE_URL}"
else
    echo "❌ Server is not running. Start with:"
    echo "   python bot/dashboard_server.py"
    echo "   or"
    echo "   python bot/user_dashboard_api.py"
    exit 1
fi

echo ""
echo "🧪 Testing Aggregated Endpoints:"
echo "================================"

# Test endpoints
ENDPOINTS=(
    "/api/aggregated/summary"
    "/api/aggregated/performance?days=7"
    "/api/aggregated/positions"
    "/api/aggregated/statistics"
    "/api/aggregated/traceability?hours=24&limit=10"
)

for endpoint in "${ENDPOINTS[@]}"; do
    echo ""
    echo "Testing: ${endpoint}"

    http_code=$(curl -s -o /dev/null -w "%{http_code}" "${BASE_URL}${endpoint}")

    if [ "$http_code" = "200" ]; then
        echo "  ✅ Status: ${http_code} OK"

        # Get a sample of the response
        response=$(curl -s "${BASE_URL}${endpoint}" | jq -r '.timestamp // .error // "No timestamp"' 2>/dev/null)
        echo "  📊 Response: ${response}"
    elif [ "$http_code" = "503" ]; then
        echo "  ⚠️  Status: ${http_code} Service Unavailable (modules not loaded)"
    else
        echo "  ❌ Status: ${http_code} FAILED"

        # Show error message
        error=$(curl -s "${BASE_URL}${endpoint}" | jq -r '.error // "Unknown error"' 2>/dev/null)
        echo "  ❌ Error: ${error}"
    fi
done

echo ""
echo "🌐 Testing HTML Dashboard:"
echo "=========================="

echo ""
echo "Dashboard URL: ${BASE_URL}/reports/aggregated"

http_code=$(curl -s -o /dev/null -w "%{http_code}" "${BASE_URL}/reports/aggregated")

if [ "$http_code" = "200" ]; then
    echo "✅ Dashboard is accessible"
    echo "📱 Open in browser: ${BASE_URL}/reports/aggregated"
else
    echo "❌ Dashboard not accessible (status: ${http_code})"
fi

echo ""
echo "📊 Summary:"
echo "==========="
echo "Aggregated reporting endpoints: ${#ENDPOINTS[@]}"
echo "Stakeholder dashboard: /reports/aggregated"
echo ""
echo "📖 For full documentation, see: AGGREGATED_REPORTING.md"
echo ""
