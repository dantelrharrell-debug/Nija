#!/bin/bash
set -e

echo "[INFO] Starting NIJA Trading Bot..."

# Test Coinbase import
python - <<END
try:
    import coinbase_advanced
    print("[INFO] Coinbase import SUCCESS")
except ModuleNotFoundError:
    print("[ERROR] Coinbase import FAILED")
END

# Start Gunicorn
# Replace 'web_service' with your Flask file name (without .py)
gunicorn --bind 0.0.0.0:5000 web_service:app
