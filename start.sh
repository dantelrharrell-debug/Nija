#!/bin/bash
set -euo pipefail

# Ensure secrets directory exists and write PEM if provided via env
mkdir -p /opt/render/project/secrets

if [ -n "${COINBASE_PEM_CONTENT:-}" ]; then
  echo "Wrote PEM from env to /opt/render/project/secrets/coinbase.pem"
  printf "%s\n" "$COINBASE_PEM_CONTENT" > /opt/render/project/secrets/coinbase.pem
  chmod 600 /opt/render/project/secrets/coinbase.pem
else
  echo "COINBASE_PEM_CONTENT env var not set — continuing (may run in Dummy mode)"
fi

# Ensure PORT env is present for Render
export PORT=${PORT:-10000}
echo "Starting gunicorn on port $PORT"

# Use wsgi module if present (preferred), otherwise fallback to nija_live_snapshot:app
if [ -f "./wsgi.py" ]; then
  exec gunicorn -b 0.0.0.0:"$PORT" wsgi:app
else
  exec gunicorn -b 0.0.0.0:"$PORT" nija_live_snapshot:app
fi
