#!/usr/bin/env bash
set -euo pipefail

echo "=== STARTING NIJA ==="

# Use the same python interpreter that will run the app
echo "Python: $(python3 -V)"
echo "Pip: $(python3 -m pip -V)"

# Ensure latest pip + install requirements into this Python environment
python3 -m pip install --upgrade pip setuptools wheel
python3 -m pip install --no-cache-dir -r /app/requirements.txt

# Diagnostic: list coinbase related install info
python3 -m pip show coinbase-advanced-py || true
python3 -c "import pkgutil; print('coinbase-like modules:', [m.name for m in pkgutil.iter_modules() if 'coinbase' in m.name])" || true

# Start the app with gunicorn (adjust worker count as needed)
exec gunicorn --bind 0.0.0.0:${PORT:-5000} main:app --workers 2 --threads 4
