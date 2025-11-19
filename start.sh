#!/usr/bin/env bash
set -euo pipefail

echo "== start.sh: beginning container startup =="

# Require GITHUB_PAT to be set (secret)
if [ -z "${GITHUB_PAT:-}" ]; then
  echo "❌ ERROR: GITHUB_PAT not set. Set GITHUB_PAT as an environment variable in your Railway/host."
  # Exit non-zero so the deploy clearly fails until the secret is configured.
  exit 1
fi

echo "⏳ Installing coinbase-advanced from GitHub (runtime install)..."
# Install coinbase-advanced from the Coinbase GitHub repo using the PAT
python -m pip install --no-cache-dir "git+https://${GITHUB_PAT}@github.com/coinbase/coinbase-advanced-python.git"

echo "✅ coinbase-advanced installed."

# Start Gunicorn (web server)
# Use a single worker by default to keep runtime simple; increase if you understand concurrency requirements.
echo "🚀 Starting gunicorn..."
exec gunicorn -w 1 -b 0.0.0.0:5000 main:app --log-level info
