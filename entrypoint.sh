#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="/app"
VENDORED_DIR="${ROOT_DIR}/cd/vendor"

# Safe PYTHONPATH setup
export PYTHONPATH="${PYTHONPATH:-}"
export PYTHONPATH="${ROOT_DIR}:${VENDORED_DIR}:${PYTHONPATH}"

echo "PYTHONPATH=${PYTHONPATH}"

# Optional: diagnostics to check imports
python - <<'PY'
import logging
logging.basicConfig(level=logging.INFO)
for name in ("coinbase_advanced", "web.wsgi"):
    try:
        __import__(name)
        logging.info("import OK: %s", name)
    except Exception as e:
        logging.exception("import FAIL: %s", name)
PY

# Start Gunicorn
PORT="${PORT:-5000}"
exec gunicorn --config ./gunicorn.conf.py web.wsgi:app --bind "0.0.0.0:${PORT}"
