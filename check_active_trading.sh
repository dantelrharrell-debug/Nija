#!/bin/bash
#
# Quick check: Is NIJA actively trading?
#
# This script checks if NIJA is actively trading using multiple methods:
# 1. HTTP endpoint (if dashboard server is running)
# 2. Python status script (comprehensive check)
# 3. Per-broker status script (fallback)
#
# Usage: ./check_active_trading.sh
#

echo "🤖 Checking NIJA Trading Status..."
echo ""

# Method 1: Try HTTP endpoint first (if bot is running)
if command -v curl &> /dev/null; then
    echo "📡 Trying HTTP endpoint..."
    if curl -s --connect-timeout 2 http://localhost:5001/health &>/dev/null; then
        curl_health_success=$?
    else
        curl_health_success=1
    fi
    
    if [ $curl_health_success -eq 0 ]; then
        echo "✅ Dashboard server is running"
        echo ""
        echo "🌐 View in browser: http://localhost:5001/status"
        echo "📊 API endpoint: http://localhost:5001/api/trading_status"
        echo ""
        
        # Show quick status from API
        echo "Quick Status:"
        status=$(curl -s http://localhost:5001/api/trading_status)
        curl_status_success=$?
        if [ $curl_status_success -eq 0 ]; then
            # Parse JSON response (basic parsing without jq)
            trading_status=$(echo "$status" | grep -o '"trading_status":"[^"]*"' | cut -d'"' -f4)
            total_positions=$(echo "$status" | grep -o '"total_positions":[0-9]*' | cut -d':' -f2)
            trading_balance=$(echo "$status" | grep -o '"trading_balance":[0-9.]*' | cut -d':' -f2)
            
            if [ -n "$trading_status" ]; then
                echo "  Status: $trading_status"
            fi
            if [ -n "$total_positions" ]; then
                echo "  Open Positions: $total_positions"
            fi
            if [ -n "$trading_balance" ]; then
                echo "  Trading Balance: \$$trading_balance"
            fi
        fi
        echo ""
        echo "✅ For detailed status, visit: http://localhost:5001/status"
        exit 0
    else
        echo "ℹ️  Dashboard server not running on localhost:5001"
        echo ""
    fi
fi

# Method 2: Try comprehensive Python script
echo "🐍 Running comprehensive status check..."
echo ""

if [ -f "check_trading_status.py" ]; then
    python3 check_trading_status.py
    exit $?
fi

# Method 3: Fall back to per-broker script
echo "📊 Checking per-broker status..."
echo ""

if [ -f "check_active_trading_per_broker.py" ]; then
    python3 check_active_trading_per_broker.py
    exit $?
fi

# Method 4: Fall back to basic check
echo "🔍 Running basic status check..."
echo ""

if [ -f "check_if_trading_now.py" ]; then
    python3 check_if_trading_now.py
    exit $?
fi

# No scripts found
echo "❌ No status check scripts found"
echo ""
echo "📝 Available options:"
echo "  1. View web status: http://localhost:5001/status (if bot running)"
echo "  2. Check API: curl http://localhost:5001/api/trading_status"
echo "  3. View documentation: ACTIVE_TRADING_STATUS.md"
echo ""
exit 1

