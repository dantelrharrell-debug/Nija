#!/bin/bash
set -euo pipefail

# -----------------------------
# Upgrade pip
# -----------------------------
echo "🔄 Upgrading pip..."
python3 -m pip install --upgrade pip

# -----------------------------
# Ensure Coinbase client is installed
# -----------------------------
echo "📦 Installing/updating coinbase-advanced-py..."
python3 -m pip install --upgrade coinbase-advanced-py

# -----------------------------
# Write PEM file safely
# -----------------------------
echo "🔐 Handling Coinbase PEM..."
mkdir -p /opt/render/project/secrets

if [ -n "${COINBASE_PEM_CONTENT:-}" ]; then
    printf "%s\n" "$COINBASE_PEM_CONTENT" > /opt/render/project/secrets/coinbase.pem
    chmod 600 /opt/render/project/secrets/coinbase.pem
    echo "✅ PEM written to /opt/render/project/secrets/coinbase.pem"
else
    echo "⚠️ COINBASE_PEM_CONTENT not set — running in DummyClient mode"
fi

# -----------------------------
# Load environment variables
# -----------------------------
echo "🌐 Loading environment variables from .env..."
export $(grep -v '^#' .env | xargs || true)

# -----------------------------
# Ensure PORT variable exists
# -----------------------------
export PORT=${PORT:-10000}
echo "🚀 Starting Gunicorn on port $PORT..."

# -----------------------------
# Start Gunicorn
# -----------------------------
if [ -f "./wsgi.py" ]; then
    exec gunicorn -b 0.0.0.0:"$PORT" wsgi:app --workers 1 --log-level info
else
    exec gunicorn -b 0.0.0.0:"$PORT" nija_live_snapshot:app --workers 1 --log-level info
fi
