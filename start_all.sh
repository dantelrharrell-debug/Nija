#!/usr/bin/env bash
set -euo pipefail

echo "== START_ALL.SH: Starting container =="

# Check for GitHub PAT for installing coinbase-advanced
if [ -z "${GITHUB_PAT:-}" ]; then
    echo "❌ ERROR: GITHUB_PAT not set"
    exit 1
fi

# Install coinbase-advanced at runtime
echo "⏳ Installing coinbase-advanced from GitHub..."
python3 -m pip install --upgrade pip setuptools wheel
python3 -m pip install --no-cache-dir "git+https://${GITHUB_PAT}@github.com/coinbase/coinbase-advanced-python.git"

echo "✅ coinbase-advanced installed"

# Start trading bot in background
echo "⚡ Starting trading bot in background..."
python3 nija_render_worker.py &   # NOTE: & runs it in background

# Start Gunicorn to serve Flask app
echo "🚀 Starting Gunicorn..."
exec gunicorn -w 1 -b 0.0.0.0:5000 main:app --log-level info
