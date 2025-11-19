#!/usr/bin/env bash
set -euo pipefail

echo "== start_worker.sh: beginning worker startup =="

if [ -z "${GITHUB_PAT:-}" ]; then
  echo "❌ ERROR: GITHUB_PAT not set. Set GITHUB_PAT as an environment variable in your Railway/host."
  exit 1
fi

echo "⏳ Installing coinbase-advanced for worker..."
python -m pip install --no-cache-dir "git+https://${GITHUB_PAT}@github.com/coinbase/coinbase-advanced-python.git"
echo "✅ coinbase-advanced installed."

# Run the worker script
exec python nija_worker.py
