#!/usr/bin/env bash
set -euo pipefail

# load .env if exists
if [ -f .env ]; then
  echo "Loading .env"
  set -o allexport
  source .env
  set +o allexport
fi

# print environment summary (not secrets) for debugging
echo "Starting container..."
if [ -n "${COINBASE_API_KEY:-}" ] && [ -n "${COINBASE_API_SECRET:-}" ]; then
  echo "COINBASE creds present."
else
  echo "WARNING: Missing COINBASE_API_KEY or COINBASE_API_SECRET. Live trading disabled."
fi

# Ensure required packages installed (helps with iterative deploys)
python3 -m pip install --no-cache-dir --upgrade pandas numpy || true

# Launch Gunicorn (use provided CMD by default)
exec "$@"
