#!/bin/bash
echo "==================================="
echo "QUICK CONNECTION TEST"
echo "==================================="

# Load .env
set -a
source .env 2>/dev/null || true
set +a

# Activate venv and test
source .venv/bin/activate
python -u VERIFY_API_CONNECTION.py

echo ""
if [ $? -eq 0 ]; then
    echo "✅ SUCCESS! Ready to start bot."
    echo ""
    echo "Run: ./start.sh"
else
    echo "❌ FAILED! Check credentials."
fi
