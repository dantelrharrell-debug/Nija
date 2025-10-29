#!/bin/bash
set -euo pipefail

# --- Upgrade pip and install Coinbase client ---
python3 -m pip install --upgrade pip
python3 -m pip install coinbase-advanced-py

# --- Ensure secrets directory exists and write PEM if provided via env ---
mkdir -p /opt/render/project/secrets

if [ -n "${COINBASE_PEM_CONTENT:-}" ]; then
  printf "%s\n" "$COINBASE_PEM_CONTENT" > /opt/render/project/secrets/coinbase.pem
  chmod 600 /opt/render/project/secrets/coinbase.pem
  echo "Wrote PEM from env to /opt/render/project/secrets/coinbase.pem"
else
  echo "COINBASE_PEM_CONTENT env var not set — continuing (may run in Dummy mode)"
fi

# --- Load other environment variables from .env safely ---
if [ -f ".env" ]; then
  echo "Loading environment variables from .env"
  # Only parse lines in KEY=VALUE format, skip lines starting with # and empty lines
  while IFS='=' read -r key value; do
    if [[ -n "$key" && "$key" != \#* ]]; then
      # Export each key-value pair
      export "$key=$value"
    fi
  done < <(grep -v '^#' .env | grep -v '^$')
fi

# --- Ensure PORT env is present for Render ---
export PORT=${PORT:-10000}
echo "Starting gunicorn on port $PORT"

# --- Start Gunicorn ---
if [ -f "./wsgi.py" ]; then
  exec gunicorn -b 0.0.0.0:"$PORT" wsgi:app --workers 1 --log-level info
else
  exec gunicorn -b 0.0.0.0:"$PORT" nija_live_snapshot:app --workers 1 --log-level info
fi
