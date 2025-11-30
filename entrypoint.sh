#!/bin/bash
set -e

# Optional: log environment info
echo "Starting NIJA Bot..."
echo "PYTHONPATH: $PYTHONPATH"
echo "Current dir: $(pwd)"

# Start Gunicorn pointing to your WSGI app
gunicorn -c gunicorn.conf.py app.wsgi:app
