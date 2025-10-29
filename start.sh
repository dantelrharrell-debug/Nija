#!/bin/bash
set -e

# Write Coinbase PEM from secret env into file (permission-safe)
mkdir -p /opt/render/project/secrets
if [ -n "$COINBASE_PEM_CONTENT" ]; then
  printf "%s\n" "$COINBASE_PEM_CONTENT" > /opt/render/project/secrets/coinbase.pem
  chmod 600 /opt/render/project/secrets/coinbase.pem
  echo "[start.sh] Wrote PEM to /opt/render/project/secrets/coinbase.pem"
fi

# Ensure PORT is set by Render
export PORT=${PORT:-10000}
exec gunicorn -b 0.0.0.0:$PORT nija_live_snapshot:app
