#!/usr/bin/env bash
set -euo pipefail
IFS=$'\n\t'

echo "=== START_ALL.SH: $(date -u) ==="

# Show Python and env info
echo "PYTHON: $(which python) $(python --version 2>&1 || true)"
echo "ENV SAMPLE: COINBASE_API_KEY=${COINBASE_API_KEY:-<missing>}"
echo "PWD: $(pwd)"
ls -la /app || true

# Pre-check main import (logs errors if any)
python -c "import sys, traceback; \
try: import main; print('main import OK'); \
except Exception as e: traceback.print_exc(); sys.exit(1)"

# Start gunicorn with full logging to console
exec gunicorn main:app \
  --bind 0.0.0.0:5000 \
  --workers 2 \
  --timeout 30 \
  --log-level debug \
  --access-logfile - \
  --error-logfile -
