#!/usr/bin/env bash
set -euo pipefail

echo "[NIJA BOT] start_bot.sh: starting"

# Check required env vars early
: "${GITHUB_PAT:?GITHUB_PAT environment variable is required (set it in Railway/Render)}"
: "${COINBASE_API_KEY:?COINBASE_API_KEY is required}"
: "${COINBASE_API_SECRET:?COINBASE_API_SECRET is required}"
: "${COINBASE_ACCOUNT_ID:?COINBASE_ACCOUNT_ID is required}"

echo "[NIJA BOT] Installing coinbase-advanced from GitHub (runtime)..."
python3 -m pip install --upgrade pip setuptools wheel
# use --no-cache-dir so PAT won't linger in wheel cache
python3 -m pip install --no-cache-dir "git+https://${GITHUB_PAT}@github.com/coinbase/coinbase-advanced-python.git"

echo "[NIJA BOT] coinbase-advanced installed. Starting bot..."

# Run the bot (unbuffered so logs appear immediately). Use exec so PID 1 is python and receives signals.
exec python3 -u /app/bot.py
