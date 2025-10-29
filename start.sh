#!/bin/bash
set -euo pipefail

# Ensure secrets directory exists
mkdir -p /opt/render/project/secrets

# Write PEM from env if set
if [ -n "${COINBASE_PEM_CONTENT:-}" ]; then
  echo "✅ PEM written to /opt/render/project/secrets/coinbase.pem"
  printf "%s\n" "$COINBASE_PEM_CONTENT" > /opt/render/project/secrets/coinbase.pem
  chmod 600 /opt/render/project/secrets/coinbase.pem
else
  echo "⚠️ COINBASE_PEM_CONTENT env var not set — continuing (Dummy mode)"
fi

# Load simple .env variables
export $(grep -v '^#' .env | xargs)

# Set PORT default for Render
export PORT=${PORT:-10000}

# Start Gunicorn
exec gunicorn -b 0.0.0.0:"$PORT" nija_live_snapshot:app --workers 1 --log-level info
