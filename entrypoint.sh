#!/bin/bash
set -e

echo "=== STARTING NIJA TRADING BOT ==="

# Pre-flight check for coinbase_advanced
python3 - <<END
import logging
logging.basicConfig(level=logging.INFO)
try:
    from coinbase_advanced.client import Client
    logging.info("coinbase_advanced module loaded successfully ✅")
except ModuleNotFoundError:
    logging.error("coinbase_advanced module NOT installed ❌. Live trading disabled!")
END

# Run Gunicorn to serve Flask application
exec gunicorn --config ./gunicorn.conf.py wsgi:app
