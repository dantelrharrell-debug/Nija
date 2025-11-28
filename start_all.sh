#!/bin/bash
set -e  # exit on error

echo "=== STARTING NIJA TRADING BOT CONTAINER ==="

# 1️⃣ Print environment variables for debug
echo "COINBASE_API_KEY=${COINBASE_API_KEY}"
echo "COINBASE_API_SECRET=${COINBASE_API_SECRET}"
echo "COINBASE_API_SUB=${COINBASE_API_SUB}"

# 2️⃣ Run the funded account check
echo "Running funded account check..."
python3 /app/check_funded.py
RESULT=$?

if [ $RESULT -ne 0 ]; then
    echo "❌ No funded account detected. Container will exit."
    exit 1
fi

# 3️⃣ Start Gunicorn if funded account exists
echo "✅ Funded account verified. Starting Gunicorn..."
exec gunicorn --config /app/gunicorn.conf.py wsgi:app
