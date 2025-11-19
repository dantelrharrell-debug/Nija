#!/usr/bin/env bash
set -euo pipefail

echo "[NIJA] Starting Nija Trading Bot..."

# Ensure environment variables are present
if [ -z "${GITHUB_PAT:-}" ]; then
  echo "❌ ERROR: GITHUB_PAT not set."
  exit 1
fi

# Install coinbase-advanced at runtime
python3 -m pip install --no-cache-dir "git+https://${GITHUB_PAT}@github.com/coinbase/coinbase-advanced-python.git"

# Run the trading bot
python3 nija_render_worker.py
