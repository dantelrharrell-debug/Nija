#!/bin/bash
set -e

echo "[INFO] Starting NIJA Trading Bot pre-flight checks..."

python3 - << 'EOF'
import sys
try:
    import coinbase_advanced
    from coinbase_advanced.client import Client
    print("[INFO] Coinbase Advanced IMPORT SUCCESS ✓")
except Exception as e:
    print("[ERROR] Coinbase import FAILED ✗")
    print(e)
    # continue - app will run in limited mode
EOF

echo "[INFO] Launching Gunicorn..."
# small number of workers so we don't spawn dozens on the platform
exec gunicorn --workers 3 --threads 2 --bind 0.0.0.0:5000 app:app
