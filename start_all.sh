#!/usr/bin/env bash
set -euo pipefail

echo "== START_ALL.SH: Starting container =="

# If you need to install coinbase-advanced from GitHub at runtime, uncomment the block below.
# Make sure GITHUB_PAT is set in your environment **before** deploy if you uncomment.

if [ "${INSTALL_COINBASE_ADVANCED:-0}" = "1" ]; then
  if [ -z "${GITHUB_PAT:-}" ]; then
    echo "❌ ERROR: GITHUB_PAT not set but INSTALL_COINBASE_ADVANCED=1"
    exit 1
  fi
  echo "⏳ Installing coinbase-advanced from GitHub..."
  python -m pip install --no-cache-dir "git+https://${GITHUB_PAT}@github.com/coinbase/coinbase-advanced-python.git"
  echo "✅ coinbase-advanced installed"
fi

# Start trading bot in background and send its logs to container stdout/stderr
echo "⚡ Starting trading bot..."
# Start the bot and ensure logs appear in your container logs:
# - stdout to container stdout, stderr to container stderr
python -u nija_render_worker.py >> /proc/1/fd/1 2>> /proc/1/fd/2 &

# Give bot a couple seconds to initialize and emit logs
sleep 3

# Start Gunicorn serving 'main:app' — use python -m to avoid PATH issues
echo "🚀 Starting Gunicorn..."
exec python -m gunicorn -w 1 -b 0.0.0.0:5000 main:app --log-level info
