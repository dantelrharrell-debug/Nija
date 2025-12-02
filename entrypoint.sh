#!/bin/bash
set -e

# Load environment variables from .env if it exists
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi

# Check required Coinbase credentials
REQUIRED_VARS=("COINBASE_API_KEY" "COINBASE_API_SECRET" "COINBASE_API_PASSPHRASE")
for VAR in "${REQUIRED_VARS[@]}"; do
    if [ -z "${!VAR}" ]; then
        echo "ERROR: Missing environment variable: $VAR"
        exit 1
    fi
done

echo "All required Coinbase credentials are set."

# Start Gunicorn
exec gunicorn web.wsgi:app \
    --bind 0.0.0.0:5000 \
    --workers 2 \
    --threads 2 \
    --worker-class gthread \
    --log-level debug \
    --capture-output
