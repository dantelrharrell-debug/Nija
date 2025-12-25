#!/bin/bash
set -e

echo "Testing .env file loading..."
echo ""

# Test loading .env
if [ -f .env ]; then
    echo "✅ .env file exists"
    
    # Load without set -a to avoid executing content
    export $(grep -v '^#' .env | xargs -0)
    
    if [ -n "$COINBASE_API_KEY" ]; then
        echo "✅ COINBASE_API_KEY loaded: ${COINBASE_API_KEY:0:40}..."
    else
        echo "❌ COINBASE_API_KEY not loaded"
    fi
    
    if [ -n "$COINBASE_API_SECRET" ]; then
        echo "✅ COINBASE_API_SECRET loaded (${#COINBASE_API_SECRET} chars)"
        echo "   First line: ${COINBASE_API_SECRET:0:30}..."
    else
        echo "❌ COINBASE_API_SECRET not loaded"
    fi
else
    echo "❌ .env file not found"
    exit 1
fi

echo ""
echo "Now test connection..."
source .venv/bin/activate
python -u VERIFY_API_CONNECTION.py
