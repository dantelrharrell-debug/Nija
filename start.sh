#!/bin/bash
# Write Coinbase PEM from secret to file
mkdir -p /opt/render/project/secrets
echo "$COINBASE_PEM_CONTENT" > /opt/render/project/secrets/coinbase.pem
chmod 600 /opt/render/project/secrets/coinbase.pem

# Start the bot (Flask + Gunicorn example)
export PORT=${PORT:-10000}
gunicorn -b 0.0.0.0:$PORT nija_live_snapshot:app
