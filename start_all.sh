#!/bin/bash
set -e

echo "[INFO] Starting NIJA Trading Bot..."

# Optional: test Coinbase import (won’t fail the build)
python - <<'END'
try:
    from coinbase_advanced.client import Client
    print("Coinbase import OK")
except Exception as e:
    print("Coinbase import FAILED:", e)
END

# Start Flask app via Gunicorn
python -m gunicorn app:app --bind 0.0.0.0:5000 --workers 2
