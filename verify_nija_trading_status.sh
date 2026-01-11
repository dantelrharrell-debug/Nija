#!/bin/bash
#
# NIJA Trading Status Verification Wrapper
# ========================================
# 
# This script loads environment variables from .env and runs the verification script.
#
# Date: January 11, 2026
#

set -e

echo ""
echo "======================================================================"
echo "    NIJA TRADING STATUS VERIFICATION"
echo "======================================================================"
echo ""

# Check if .env exists
if [ ! -f .env ]; then
    echo "❌ ERROR: .env file not found!"
    echo ""
    echo "   Please create a .env file with your API credentials."
    echo "   See .env.example for reference."
    echo ""
    exit 1
fi

# Load environment variables
echo "📂 Loading environment variables from .env..."
set -a
source .env
set +a

echo "✅ Environment variables loaded"
echo ""

# Run the Python verification script
echo "🔍 Running verification checks..."
echo ""

python3 verify_nija_trading_status_jan_11_2026.py

status=$?

echo ""
echo "======================================================================"
echo ""

exit $status
