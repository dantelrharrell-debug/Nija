#!/bin/bash

# --- Write Coinbase PEM from secret to file ---
mkdir -p /opt/render/project/secrets
echo "$COINBASE_PEM_CONTENT" > /opt/render/project/secrets/coinbase.pem
chmod 600 /opt/render/project/secrets/coinbase.pem

# --- Export environment variables (if not already in Render dashboard) ---
export COINBASE_API_KEY=${COINBASE_API_KEY}
export COINBASE_PASSPHRASE=${COINBASE_PASSPHRASE}
export COINBASE_API_SECRET=${COINBASE_API_SECRET}  # optional if using RESTClient

# --- Start the Flask app via Gunicorn ---
export PORT=${PORT:-10000}
gunicorn -b 0.0.0.0:$PORT nija_live_snapshot:app
