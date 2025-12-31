#!/bin/bash
#
# NIJA Comprehensive System Check
# Wrapper script for comprehensive_nija_check.py
#
# Usage: ./check_nija_comprehensive.sh
#

echo "🔍 Running comprehensive NIJA system check..."
echo ""

python3 comprehensive_nija_check.py

exit_code=$?

echo ""
echo "======================================================================"
if [ $exit_code -eq 0 ]; then
    echo "✅ Check completed successfully"
else
    echo "⚠️  Check completed with warnings - review output above"
fi
echo "======================================================================"

exit $exit_code
