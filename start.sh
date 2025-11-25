#!/usr/bin/env bash
set -euo pipefail

echo "== start.sh: beginning container startup =="

# Install coinbase-advanced-py from PyPI
python3 -m pip install --no-cache-dir coinbase-advanced-py==1.8.2
echo "✅ coinbase-advanced-py installed"

# Start Gunicorn web server
exec gunicorn -w 1 -b 0.0.0.0:5000 main:app --log-level info
