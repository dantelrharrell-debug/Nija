#!/bin/bash
set -e

# -------------------------------
# Load environment variables
# -------------------------------
if [ -f .env ]; then
  export $(grep -v '^#' .env | xargs)
fi

# -------------------------------
# Check Coinbase credentials
# -------------------------------
if [ -n "$COINBASE_API_KEY" ] && [ -n "$COINBASE_API_SECRET" ] && [ -n "$COINBASE_API_PASSPHRASE" ]; then
    echo "Live trading enabled."
else
    echo "Live trading disabled: missing credentials."
fi

# -------------------------------
# Start Gunicorn
# -------------------------------
exec gunicorn wsgi:app -c gunicorn.conf.py
