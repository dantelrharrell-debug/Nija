#!/bin/bash
# Ensure PEM directory exists
mkdir -p /opt/render/project/secrets

# Write Coinbase PEM from secret to file
if [ -z "$COINBASE_PEM_CONTENT" ]; then
  echo "[ERROR] COINBASE_PEM_CONTENT is not set!"
  exit 1
fi

echo "$COINBASE_PEM_CONTENT" > /opt/render/project/secrets/coinbase.pem
chmod 600 /opt/render/project/secrets/coinbase.pem

# Export port for Gunicorn
export PORT=${PORT:-10000}

# Start the Flask app via Gunicorn
exec gunicorn -b 0.0.0.0:$PORT nija_live_snapshot:app
