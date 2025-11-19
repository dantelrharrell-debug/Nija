#!/usr/bin/env bash
set -euo pipefail

echo "== start.sh: beginning container startup =="

if [ -z "${GITHUB_PAT:-}" ]; then
  echo "❌ ERROR: GITHUB_PAT not set"
  exit 1
fi

# Install coinbase-advanced from GitHub
python3 -m pip install --no-cache-dir "git+https://${GITHUB_PAT}@github.com/coinbase/coinbase-advanced-python.git"
echo "✅ coinbase-advanced installed"

# Start Gunicorn web server
exec gunicorn -w 1 -b 0.0.0.0:5000 main:app --log-level info
