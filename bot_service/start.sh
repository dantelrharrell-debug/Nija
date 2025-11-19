#!/bin/bash
set -e

# Install coinbase-advanced at runtime
if ! pip show coinbase-advanced > /dev/null 2>&1; then
    echo "Installing coinbase-advanced..."
    pip install --no-cache-dir git+https://$GITHUB_PAT@github.com/coinbase/coinbase-advanced-python.git
fi

# Start the trading bot
echo "Starting Nija Trading Bot..."
python nija_render_worker.py
