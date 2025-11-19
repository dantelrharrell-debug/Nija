#!/usr/bin/env bash
set -euo pipefail

echo "== START_BOT.SH: Starting container =="

# Check GITHUB_PAT
if [ -z "${GITHUB_PAT:-}" ]; then
    echo "❌ ERROR: GITHUB_PAT not set"
    exit 1
fi

# Install coinbase-advanced
echo "⏳ Installing coinbase-advanced..."
python3 -m pip install --no-cache-dir "git+https://${GITHUB_PAT}@github.com/coinbase/coinbase-advanced-python.git"
echo "✅ coinbase-advanced installed"

# Start bot and redirect output to stdout/stderr
echo "⚡ Starting bot worker..."
python3 bot.py >> /proc/1/fd/1 2>> /proc/1/fd/2 &

# Give bot a few seconds to start
sleep 5

# Start Gunicorn
echo "🚀 Starting Gunicorn..."
exec gunicorn -w 1 -b 0.0.0.0:5000 main:app --log-level info
