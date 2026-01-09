#!/bin/bash
# Quick script to check if NIJA is trading for user #1
# Usage: ./check_user1_trading.sh

echo ""
echo "Checking if NIJA is trading for user #1..."
echo ""

python is_user1_trading.py

exit_code=$?

if [ $exit_code -eq 0 ]; then
    echo ""
    echo "✅ User #1 is trading!"
    echo ""
elif [ $exit_code -eq 1 ]; then
    echo ""
    echo "❌ User #1 is NOT trading. See steps above to enable."
    echo ""
else
    echo ""
    echo "⚠️  Error checking user status. See error details above."
    echo ""
fi

exit $exit_code
