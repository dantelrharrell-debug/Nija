#!/usr/bin/env bash
set -euo pipefail

echo "=== STARTING NIJA TRADING BOT CONTAINER ==="

# Add vendored path to PYTHONPATH (helps imports during runtime)
export PYTHONPATH="$PYTHONPATH:/app/cd/vendor/coinbase_advanced:/app/cd/vendor/coinbase_advanced_py"

# Quick runtime check for coinbase_advanced
python - <<'PY'
import sys, logging
logging.basicConfig(level=logging.INFO)
try:
    import coinbase_advanced
    logging.info("coinbase_advanced import OK ✅")
except Exception as e:
    logging.error("coinbase_advanced import FAILED ❌: %s", e)
    # not exiting: container can still serve dashboard/status
PY

# Start Gunicorn; prefer web.wsgi:app
exec gunicorn --config ./gunicorn.conf.py web.wsgi:app
