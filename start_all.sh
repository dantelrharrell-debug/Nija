#!/usr/bin/env bash
set -euo pipefail

echo "Starting Coinbase Advanced install..."
python3 -m pip install --no-cache-dir "git+https://${GITHUB_PAT}@github.com/coinbase/coinbase-advanced-python.git"

echo "Starting trading bot in background..."
python3 nija_render_worker.py &

echo "Starting web server..."
exec gunicorn -w 1 -b 0.0.0.0:$PORT main:app --log-level info
