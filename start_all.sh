#!/bin/bash
set -e

echo "[INFO] Starting NIJA Trading Bot pre-flight checks..."

# Check Coinbase module
python3 - <<END
import logging
try:
    import coinbase_advanced
    print("[INFO] Coinbase import SUCCESS")
except ModuleNotFoundError:
    logging.error("[ERROR] Coinbase import FAILED — continuing in limited mode")
END

# Start Gunicorn with limited workers (avoid flooding)
exec gunicorn --workers 3 --bind 0.0.0.0:5000 app:app
