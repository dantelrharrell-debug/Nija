#!/usr/bin/env bash
set -euo pipefail

echo "[NIJA-BOT] start_bot.sh starting..."

# Required env checks
if [ -z "${GITHUB_PAT:-}" ]; then
  echo "❌ ERROR: GITHUB_PAT is not set. Set GITHUB_PAT in this service's environment and redeploy."
  exit 1
fi

if [ -z "${COINBASE_API_KEY:-}" ] || [ -z "${COINBASE_API_SECRET:-}" ] || [ -z "${COINBASE_ACCOUNT_ID:-}" ]; then
  echo "❌ ERROR: Missing COINBASE_API_KEY / COINBASE_API_SECRET / COINBASE_ACCOUNT_ID in env."
  exit 1
fi

# Install coinbase-advanced at runtime (uses GITHUB_PAT to access the repo)
echo "[NIJA-BOT] Installing coinbase-advanced from GitHub..."
python -m pip install --no-cache-dir "git+https://${GITHUB_PAT}@github.com/coinbase/coinbase-advanced-python.git" || {
  echo "❌ ERROR: Failed to install coinbase-advanced"
  exit 1
}
echo "✅ coinbase-advanced installed"

# Run bot - keep logs on stdout/stderr
echo "[NIJA-BOT] Launching bot..."
exec python3 /app/bot.py
