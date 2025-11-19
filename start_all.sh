#!/bin/bash
set -euo pipefail

echo "[NIJA] Installing Coinbase Advanced SDK..."
if [ -z "${GITHUB_PAT:-}" ]; then
  echo "❌ GITHUB_PAT environment variable is missing"
  exit 1
fi

python3 -m pip install --upgrade pip
python3 -m pip install "git+https://${GITHUB_PAT}@github.com/coinbase/coinbase-advanced-python.git"

# Start bot in background
echo "[NIJA] Starting trading bot..."
python3 nija_render_worker.py &

# Start web server
echo "[NIJA] Starting Gunicorn..."
exec gunicorn -w 1 -b 0.0.0.0:5000 main:app --log-level info
