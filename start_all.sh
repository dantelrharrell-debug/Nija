#!/bin/bash
set -e

echo "=== STARTING NIJA TRADING BOT CONTAINER ==="

# Run funded account check
echo "Running funded account check..."
python3 /app/check_funded.py || { echo "❌ Funded account check failed"; exit 1; }

echo "✅ Funded account verified. Starting Gunicorn..."
exec gunicorn --config /app/gunicorn.conf.py wsgi:app
