#!/bin/bash
set -e

echo "=== STARTING NIJA TRADING BOT ==="

# Run a small Python pre-flight check
python3 - <<'END_PY'
import sys
import os
import logging

logging.basicConfig(level=logging.INFO)

# Adjust this path if your vendored copy is somewhere else
VENDORED_PATH = os.path.abspath("./cd/vendor/coinbase_advanced_py")
if VENDORED_PATH not in sys.path:
    sys.path.insert(0, VENDORED_PATH)
    logging.info(f"Added vendored path to sys.path: {VENDORED_PATH}")

try:
    from coinbase_advanced.client import Client
    logging.info("coinbase_advanced module loaded successfully ✅ Live trading ENABLED")
except ModuleNotFoundError as e:
    logging.error("coinbase_advanced module NOT installed ❌ Live trading DISABLED")
    logging.error(repr(e))
END_PY

# Determine Gunicorn WSGI path
if [ -f app/wsgi.py ]; then
    WSGI_MODULE="app.wsgi:app"
elif [ -f wsgi.py ]; then
    WSGI_MODULE="wsgi:app"
else
    echo "No wsgi file found, exiting"
    exit 1
fi

# Start Gunicorn
exec gunicorn --config ./gunicorn.conf.py "$WSGI_MODULE"
