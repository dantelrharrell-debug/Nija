#!/bin/bash
set -e

echo "[INFO] Starting NIJA Trading Bot..."

# Optional: run a simple Coinbase import test
python - <<'END'
try:
    from coinbase_advanced.client import Client
    print("Coinbase import OK")
except Exception as e:
    print("Coinbase import FAILED:", e)
END

# Start Gunicorn via python -m to avoid PATH issues
exec python -m gunicorn app:app --bind 0.0.0.0:5000 --workers 2
