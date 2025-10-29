#!/bin/bash
set -euo pipefail

# Write Coinbase PEM from secret content (if provided)
mkdir -p /opt/render/project/secrets
if [ -n "${COINBASE_PEM_CONTENT-}" ]; then
  echo "$COINBASE_PEM_CONTENT" > /opt/render/project/secrets/coinbase.pem
  chmod 600 /opt/render/project/secrets/coinbase.pem
  echo "Wrote PEM to /opt/render/project/secrets/coinbase.pem"
fi

# If you prefer to provide a file path instead of content:
# set COINBASE_API_SECRET_PATH=/opt/render/project/secrets/coinbase.pem in Render env.

export PORT=${PORT:-10000}
echo "Starting gunicorn on port $PORT"
exec gunicorn -b 0.0.0.0:$PORT nija_live_snapshot:app
