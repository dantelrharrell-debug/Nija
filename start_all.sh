#!/bin/bash
set -e

# Ensure we are in /app
cd /app || exit 1

# Verify critical files exist
if [ ! -f nija_client.py ] || [ ! -f check_funded.py ]; then
    echo "[ERROR] nija_client.py or check_funded.py missing in /app!"
    ls -l /app
    exit 1
fi

# Start Gunicorn
exec gunicorn -c gunicorn_conf.py wsgi:app
