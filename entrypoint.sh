#!/bin/bash
set -e  # exit immediately on any error

echo "=== STARTING NIJA TRADING BOT ==="

# Test Coinbase connection
python3 -c "
import sys
try:
    from coinbase_advanced.client import Client
    print('coinbase_advanced module loaded successfully.')
except ModuleNotFoundError:
    print('ERROR: coinbase_advanced module NOT installed!')
    # Uncomment the next line if you want to stop the container when missing
    # sys.exit(1)
"

# Start Gunicorn
exec gunicorn --config ./gunicorn.conf.py wsgi:app
