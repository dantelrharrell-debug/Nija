#!/usr/bin/env bash
set -euo pipefail

echo "== START_ALL.SH: Starting container =="

if [ -z "${GITHUB_PAT:-}" ]; then
  echo "❌ ERROR: GITHUB_PAT not set. Add as a secret in Railway/Render and redeploy."
  exit 1
fi

echo "⏳ Installing coinbase-advanced from GitHub..."
python3 -m pip install --upgrade pip setuptools wheel
python3 -m pip install --no-cache-dir "git+https://${GITHUB_PAT}@github.com/coinbase/coinbase-advanced-python.git"

echo "✅ coinbase-advanced installed"

# Start trading bot (background)
echo "⚡ Starting trading worker..."
python3 nija_render_worker.py &

# Start API (gunicorn)
echo "🚀 Starting Gunicorn..."
exec gunicorn -w 1 -b 0.0.0.0:5000 main:app --log-level info
