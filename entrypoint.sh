#!/bin/bash
set -euo pipefail

echo "=== STARTING NIJA TRADING BOT CONTAINER ==="

# Safely ensure PYTHONPATH contains /app and the vendored folder (won't error if PYTHONPATH was unset)
export PYTHONPATH="${PYTHONPATH:-}:/app:/app/cd/vendor/coinbase_advanced_py"
# Optional: normalize (remove leading colon if PYTHONPATH was empty)
PYTHONPATH="${PYTHONPATH#:}"
export PYTHONPATH

echo "PYTHONPATH=$PYTHONPATH"

# Quick runtime check for coinbase module (non-fatal)
python - <<'PY'
import sys, logging
logging.basicConfig(level=logging.INFO)
loaded = False
# Try the likely module names in order
for mod in ("coinbase_advanced", "coinbase_advanced_py", "coinbase_advanced.client", "coinbase_advanced_py.client"):
    try:
        __import__(mod)
        logging.info("Loaded coinbase module: %s", mod)
        loaded = True
        break
    except Exception as e:
        logging.debug("Import failed for %s (%s)", mod, e)
if not loaded:
    logging.error("coinbase_advanced module NOT installed. Live trading disabled")
PY

# Start Gunicorn — point to the wsgi your config expects
exec gunicorn -c gunicorn.conf.py web.wsgi:app
