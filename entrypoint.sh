#!/bin/bash
set -e

echo "=== STARTING NIJA TRADING BOT CONTAINER ==="

# Optional: Check Coinbase module
python -c "import sys; sys.path.append('/app/app/cd/vendor/coinbase_advanced_py'); import coinbase_advanced" 2>/dev/null || \
echo "coinbase_advanced module NOT installed ❌. Live trading disabled"

# Start Gunicorn
exec gunicorn -c gunicorn.conf.py app.wsgi:app
