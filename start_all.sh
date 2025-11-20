#!/usr/bin/env bash
set -euo pipefail

echo "== START_ALL.SH: Starting container =="

if [ -z "${GITHUB_PAT:-}" ]; then
  echo "❌ ERROR: GITHUB_PAT not set. Set it in your deployment provider secrets."
  exit 1
fi

echo "⏳ Installing coinbase-advanced from GitHub (runtime)..."
python3 -m pip install --upgrade pip setuptools wheel
python3 -m pip install --no-cache-dir "git+https://${GITHUB_PAT}@github.com/coinbase/coinbase-advanced-python.git" || {
  echo "❌ Failed to install coinbase-advanced (check GITHUB_PAT and network)."
  exit 1
}
echo "✅ coinbase-advanced installed"

echo "⚡ Starting trading bot in background..."
python3 nija_render_worker.py &

echo "🚀 Starting Gunicorn..."
exec gunicorn -w 1 -b 0.0.0.0:5000 main:app --log-level info
