#!/usr/bin/env bash
set -euo pipefail

if [ -z "${GITHUB_PAT:-}" ]; then
  echo "❌ GITHUB_PAT not set. If coinbase-advanced needs to be installed at runtime, set GITHUB_PAT."
  exit 1
fi

echo "⏳ Installing coinbase-advanced..."
python -m pip install --no-cache-dir "git+https://${GITHUB_PAT}@github.com/coinbase/coinbase-advanced-python.git"
echo "✅ coinbase-advanced installed"

echo "⚡ Starting bot..."
exec python -u nija_render_worker.py
