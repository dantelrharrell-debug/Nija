#!/bin/bash
# Quick check script for Kraken connection status
# Usage: ./check_kraken_status.sh

echo "Checking Kraken connection status for NIJA..."
echo ""

python3 check_kraken_status.py
exit_code=$?

echo ""
if [ $exit_code -eq 0 ]; then
    echo "✅ All Kraken accounts are configured and ready to trade"
elif [ $exit_code -eq 1 ]; then
    echo "⚠️  Some Kraken accounts are configured, but not all"
else
    echo "❌ No Kraken accounts are configured"
fi

exit $exit_code
