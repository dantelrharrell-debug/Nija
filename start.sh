#!/bin/bash
set -euo pipefail

# -------------------------------
# Upgrade pip and ensure Coinbase client is installed
# -------------------------------
python3 -m pip install --upgrade pip
python3 -m pip install coinbase-advanced-py

# -------------------------------
# Load environment variables from .env
# -------------------------------
if [ -f ".env" ]; then
  export $(grep -v '^#' .env | xargs)
  echo "Loaded environment variables from .env"
else
  echo ".env file not found — please add it!"
  exit 1
fi

# -------------------------------
# Ensure secrets directory exists and write PEM file
# -------------------------------
mkdir -p /opt/render/project/secrets

if [ -n "${COINBASE_PEM_CONTENT:-}" ]; then
  printf "%s\n" "$COINBASE_PEM_CONTENT" > /opt/render/project/secrets/coinbase.pem
  chmod 600 /opt/render/project/secrets/coinbase.pem
  echo "Wrote PEM to /opt/render/project/secrets/coinbase.pem"
else
  echo "COINBASE_PEM_CONTENT not set — bot will run in Dummy mode!"
fi

# -------------------------------
# Ensure PORT env is present for Render
# -------------------------------
export PORT=${PORT:-10000}
echo "Starting Gunicorn on port $PORT"

# -------------------------------
# Start Gunicorn
# -------------------------------
# Prefer wsgi.py if it exists
if [ -f "./wsgi.py" ]; then
  exec gunicorn -b 0.0.0.0:"$PORT" wsgi:app --workers 1 --log-level info
else
  exec gunicorn -b 0.0.0.0:"$PORT" nija_live_snapshot:app --workers 1 --log-level info
fi
