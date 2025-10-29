#!/bin/bash
set -euo pipefail

# Upgrade pip
python3 -m pip install --upgrade pip
python3 -m pip install --upgrade coinbase-advanced-py

# Handle Coinbase PEM
mkdir -p /opt/render/project/secrets
if [ -n "${COINBASE_PEM_CONTENT:-}" ]; then
    printf "%s\n" "$COINBASE_PEM_CONTENT" > /opt/render/project/secrets/coinbase.pem
    chmod 600 /opt/render/project/secrets/coinbase.pem
    echo "✅ PEM written to /opt/render/project/secrets/coinbase.pem"
else
    echo "⚠️ COINBASE_PEM_CONTENT not set — running in DummyClient mode"
fi

# Load .env safely (skip multi-line PEM)
echo "🌐 Loading environment variables from .env..."
set -a
grep -v '^#' .env | grep -v 'COINBASE_PEM_CONTENT' | sed '/^\s*$/d' > /tmp/envfile
. /tmp/envfile
set +a

# Ensure PORT
export PORT=${PORT:-10000}
echo "🚀 Starting Gunicorn on port $PORT..."

# Start Gunicorn
if [ -f "./wsgi.py" ]; then
    exec gunicorn -b 0.0.0.0:"$PORT" wsgi:app --workers 1 --log-level info
else
    exec gunicorn -b 0.0.0.0:"$PORT" nija_live_snapshot:app --workers 1 --log-level info
fi
