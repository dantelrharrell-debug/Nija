#!/bin/bash
set -euo pipefail

# Ensure secrets directory exists
mkdir -p /opt/render/project/secrets

# Write PEM key from environment variable
if [ -n "${COINBASE_PEM_CONTENT:-}" ]; then
  echo "✅ PEM written to /opt/render/project/secrets/coinbase.pem"
  printf "%s\n" "$COINBASE_PEM_CONTENT" > /opt/render/project/secrets/coinbase.pem
  chmod 600 /opt/render/project/secrets/coinbase.pem
else
  echo "⚠️ COINBASE_PEM_CONTENT env var not set — continuing (DummyClient mode)"
fi

# Load simple .env variables
if [ -f ".env" ]; then
  export $(grep -v '^#' .env | xargs)
fi

# Set Render port default
export PORT=${PORT:-10000}

# Start Gunicorn with Nija app
exec gunicorn -b 0.0.0.0:"$PORT" nija_live_snapshot:app --workers 1 --log-level info
