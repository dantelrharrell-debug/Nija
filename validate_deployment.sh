#!/bin/bash
#
# NIJA Bot Deployment Validation Script
#
# Validates bot is ready for deployment and running correctly in production.
# Run this after deploying to Railway/Render to ensure everything works.
#
# Author: NIJA Trading Systems
# Date: December 19, 2025
#

set -e

echo "╔══════════════════════════════════════════════════════════════════╗"
echo "║         NIJA BOT - DEPLOYMENT VALIDATION SCRIPT                  ║"
echo "╚══════════════════════════════════════════════════════════════════╝"
echo ""

PASSED=0
FAILED=0
WARNINGS=0

# Color codes
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

pass_check() {
    echo -e "${GREEN}✅ $1${NC}"
    ((PASSED++))
}

fail_check() {
    echo -e "${RED}❌ $1${NC}"
    ((FAILED++))
}

warn_check() {
    echo -e "${YELLOW}⚠️  $1${NC}"
    ((WARNINGS++))
}

# ==================== PRE-DEPLOYMENT CHECKS ====================

echo "📋 PRE-DEPLOYMENT CHECKS"
echo "────────────────────────────────────────────────────────────────────"

# Check Python version
if command -v python3 &> /dev/null; then
    PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
    pass_check "Python installed: $PYTHON_VERSION"
else
    fail_check "Python 3 not found"
fi

# Check required files
if [ -f "bot/trading_strategy.py" ]; then
    pass_check "Trading strategy file exists"
else
    fail_check "Missing bot/trading_strategy.py"
fi

if [ -f "bot/fee_aware_config.py" ]; then
    pass_check "Fee-aware config exists"
else
    fail_check "Missing bot/fee_aware_config.py"
fi

if [ -f "requirements.txt" ]; then
    pass_check "Requirements file exists"
else
    fail_check "Missing requirements.txt"
fi

if [ -f "Dockerfile" ]; then
    pass_check "Dockerfile exists"
else
    warn_check "Dockerfile not found (optional for local)"
fi

# Check environment variables
echo ""
echo "🔐 ENVIRONMENT VARIABLES"
echo "────────────────────────────────────────────────────────────────────"

if [ -n "$COINBASE_API_KEY" ]; then
    pass_check "COINBASE_API_KEY is set"
else
    fail_check "COINBASE_API_KEY not set"
fi

if [ -n "$COINBASE_API_SECRET" ]; then
    pass_check "COINBASE_API_SECRET is set"
else
    fail_check "COINBASE_API_SECRET not set"
fi

if [ -n "$COINBASE_PEM_CONTENT" ]; then
    pass_check "COINBASE_PEM_CONTENT is set"
else
    fail_check "COINBASE_PEM_CONTENT not set"
fi

# ==================== DEPENDENCY CHECKS ====================

echo ""
echo "📦 PYTHON DEPENDENCIES"
echo "────────────────────────────────────────────────────────────────────"

# Check if we can import required packages
python3 -c "import coinbase" 2>/dev/null && pass_check "coinbase package installed" || fail_check "coinbase package missing"
python3 -c "import flask" 2>/dev/null && pass_check "flask package installed" || warn_check "flask package missing (optional for dashboard)"
python3 -c "import pandas" 2>/dev/null && pass_check "pandas package installed" || fail_check "pandas package missing"
python3 -c "import numpy" 2>/dev/null && pass_check "numpy package installed" || fail_check "numpy package missing"

# ==================== CONFIGURATION VALIDATION ====================

echo ""
echo "⚙️  BOT CONFIGURATION"
echo "────────────────────────────────────────────────────────────────────"

# Run Python health check if available
if [ -f "health_check.py" ]; then
    if python3 health_check.py > /dev/null 2>&1; then
        pass_check "Health check passed"
    else
        warn_check "Health check found issues (see health_check.py output)"
    fi
else
    warn_check "health_check.py not found"
fi

# ==================== CONNECTIVITY TESTS ====================

echo ""
echo "🔌 CONNECTIVITY TESTS"
echo "────────────────────────────────────────────────────────────────────"

# Test Coinbase API
python3 << 'EOF' 2>/dev/null
import sys
sys.path.insert(0, 'bot')
try:
    from broker_integration import CoinbaseAdvancedTradeBroker
    broker = CoinbaseAdvancedTradeBroker()
    balance = broker.get_balance()
    if balance >= 0:
        print(f"✅ Coinbase API connected - Balance: ${balance:.2f}")
        sys.exit(0)
    else:
        print("❌ Could not retrieve balance")
        sys.exit(1)
except Exception as e:
    print(f"❌ Coinbase API error: {e}")
    sys.exit(1)
EOF

if [ $? -eq 0 ]; then
    ((PASSED++))
else
    ((FAILED++))
fi

# Test market data access
python3 << 'EOF' 2>/dev/null
import sys
sys.path.insert(0, 'bot')
try:
    from broker_integration import CoinbaseAdvancedTradeBroker
    broker = CoinbaseAdvancedTradeBroker()
    price = broker.get_current_price("BTC-USD")
    if price > 0:
        print(f"✅ Market data access - BTC-USD: ${price:.2f}")
        sys.exit(0)
    else:
        print("❌ Could not get market price")
        sys.exit(1)
except Exception as e:
    print(f"❌ Market data error: {e}")
    sys.exit(1)
EOF

if [ $? -eq 0 ]; then
    ((PASSED++))
else
    ((FAILED++))
fi

# ==================== POST-DEPLOYMENT CHECKS ====================

echo ""
echo "🚀 POST-DEPLOYMENT CHECKS"
echo "────────────────────────────────────────────────────────────────────"

# Check if monitoring directory is writable
if mkdir -p /tmp/nija_monitoring 2>/dev/null; then
    touch /tmp/nija_monitoring/.test 2>/dev/null && rm /tmp/nija_monitoring/.test
    if [ $? -eq 0 ]; then
        pass_check "Monitoring directory writable"
    else
        warn_check "Cannot write to monitoring directory"
    fi
else
    warn_check "Cannot create monitoring directory"
fi

# Check if data directory is writable
if [ -d "/usr/src/app/data" ]; then
    DATA_DIR="/usr/src/app/data"
elif [ -d "./data" ]; then
    DATA_DIR="./data"
else
    DATA_DIR="./data"
    mkdir -p "$DATA_DIR" 2>/dev/null
fi

if [ -w "$DATA_DIR" ]; then
    pass_check "Data directory writable: $DATA_DIR"
else
    warn_check "Data directory not writable: $DATA_DIR"
fi

# ==================== FINAL SUMMARY ====================

echo ""
echo "╔══════════════════════════════════════════════════════════════════╗"
echo "║                     VALIDATION SUMMARY                           ║"
echo "╚══════════════════════════════════════════════════════════════════╝"
echo ""
echo -e "  ${GREEN}✅ Passed:   $PASSED${NC}"
echo -e "  ${YELLOW}⚠️  Warnings: $WARNINGS${NC}"
echo -e "  ${RED}❌ Failed:   $FAILED${NC}"
echo ""
echo "────────────────────────────────────────────────────────────────────"

if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}🎉 DEPLOYMENT VALIDATION PASSED!${NC}"
    echo ""
    echo "✅ Bot is ready for production deployment"
    if [ $WARNINGS -gt 0 ]; then
        echo "⚠️  Review warnings above for optimization opportunities"
    fi
    echo ""
    echo "📋 NEXT STEPS:"
    echo "  1. git add ."
    echo "  2. git commit -m 'Add monitoring and validation tools'"
    echo "  3. git push origin main"
    echo "  4. Monitor logs after deployment"
    echo "  5. Run 'python3 performance_analytics.py' to track results"
    echo ""
    exit 0
else
    echo -e "${RED}🚨 DEPLOYMENT VALIDATION FAILED!${NC}"
    echo ""
    echo "❌ Fix the failed checks before deploying"
    echo "📖 Review error messages above"
    echo ""
    echo "🔧 COMMON FIXES:"
    echo "  - Missing env vars: Copy .env.example to .env and configure"
    echo "  - Missing packages: pip install -r requirements.txt"
    echo "  - API issues: Verify Coinbase API credentials"
    echo ""
    exit 1
fi
