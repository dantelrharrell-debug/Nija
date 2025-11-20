#!/usr/bin/env bash
set -euo pipefail

echo "== START_BOT.SH: Starting bot container =="

if [ -z "${GITHUB_PAT:-}" ]; then
  echo "❌ ERROR: GITHUB_PAT not set. Set it in the deployment provider secrets."
  exit 1
fi

echo "⏳ Installing coinbase-advanced (runtime)..."
python3 -m pip install --upgrade pip setuptools wheel
python3 -m pip install --no-cache-dir "git+https://${GITHUB_PAT}@github.com/coinbase/coinbase-advanced-python.git" || {
  echo "❌ Failed to install coinbase-advanced"
  exit 1
}
echo "✅ coinbase-advanced installed"

echo "⚡ Launching bot..."
exec python3 nija_render_worker.py
