#!/bin/bash
set -e

# Install private repo at runtime
if [ -z "$GITHUB_PAT" ]; then
  echo "GITHUB_PAT not set! Skipping coinbase_advanced_py install..."
else
  echo "Installing coinbase_advanced_py..."
  pip install --no-cache-dir git+https://${GITHUB_PAT}@github.com/dantelrharrell-debug/coinbase_advanced_py.git
fi

# Start Gunicorn
exec gunicorn -c gunicorn.conf.py web.wsgi:app
