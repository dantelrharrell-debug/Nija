#!/bin/bash
# Start NIJA API Gateway
# This script starts the API Gateway server for mobile/web app integration

set -e  # Exit on error

echo "=============================="
echo "  STARTING NIJA API GATEWAY"
echo "=============================="

# Prefer workspace venv Python, fallback to system python3
PY=""
if [ -x ./.venv/bin/python ]; then
    PY="./.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PY="$(command -v python3)"
fi

if [ -z "$PY" ]; then
    echo "❌ No Python interpreter found (venv or system)"
    echo "   Ensure .venv exists or install python3"
    exit 127
fi

$PY --version 2>&1

# Check if FastAPI is installed
$PY -c "import fastapi; print('✅ FastAPI available')" 2>&1 || {
    echo "❌ FastAPI not installed"
    echo "   Run: pip install -r requirements.txt"
    exit 1
}

# Check if uvicorn is installed
$PY -c "import uvicorn; print('✅ Uvicorn available')" 2>&1 || {
    echo "❌ Uvicorn not installed"
    echo "   Run: pip install -r requirements.txt"
    exit 1
}

# Set default port if not specified
PORT=${PORT:-8000}

# Check for JWT_SECRET_KEY (required for production)
if [ -z "$JWT_SECRET_KEY" ]; then
    echo ""
    echo "⚠️  WARNING: JWT_SECRET_KEY environment variable not set"
    echo "   This is REQUIRED for the API Gateway to start."
    echo ""
    echo "🔧 SOLUTION:"
    echo "   Generate a secure secret:"
    echo "   python -c \"import secrets; print(secrets.token_hex(32))\""
    echo ""
    echo "   Then set it:"
    echo "   export JWT_SECRET_KEY='your-generated-secret'"
    echo ""
    echo "   Or add to .env file:"
    echo "   echo \"JWT_SECRET_KEY=your-generated-secret\" >> .env"
    echo ""
    exit 1
fi

echo ""
echo "🚀 Starting NIJA API Gateway on port $PORT"
echo "📚 API Docs: http://localhost:$PORT/api/v1/docs"
echo "🔒 Strategy: v7.2 (Locked - Profitability Mode)"
echo ""

# Start the API Gateway
exec $PY api_gateway.py
