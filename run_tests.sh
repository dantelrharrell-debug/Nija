#!/bin/bash
# Run all NIJA bot tests

echo "════════════════════════════════════════════════════════════════"
echo "🧪 NIJA BOT TEST SUITE"
echo "════════════════════════════════════════════════════════════════"
echo ""

# Change to bot directory
cd "$(dirname "$0")/bot"

# Run tests with coverage if available
if command -v python3 &> /dev/null; then
    echo "Running tests with Python 3..."
    python3 -m unittest discover -s tests -p "test_*.py" -v
    TEST_RESULT=$?
else
    echo "❌ Python 3 not found"
    exit 1
fi

echo ""
echo "════════════════════════════════════════════════════════════════"

if [ $TEST_RESULT -eq 0 ]; then
    echo "✅ ALL TESTS PASSED"
    echo "════════════════════════════════════════════════════════════════"
    exit 0
else
    echo "❌ SOME TESTS FAILED"
    echo "════════════════════════════════════════════════════════════════"
    exit 1
fi
