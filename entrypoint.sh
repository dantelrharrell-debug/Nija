#!/usr/bin/env bash
set -euo pipefail

echo "=== STARTING NIJA TRADING BOT CONTAINER ==="

ROOT_DIR="/app"
VENDORED_DIR="${ROOT_DIR}/cd/vendor"

# Ensure safe defaults for PYTHONPATH
export PYTHONPATH="${PYTHONPATH:-}"
# Add repo root and vendored dir(s)
case ":$PYTHONPATH:" in
  *":${ROOT_DIR}:"*) : ;;
  *) export PYTHONPATH="${ROOT_DIR}:${PYTHONPATH}" ;;
esac
if [ -d "${VENDORED_DIR}" ]; then
  case ":$PYTHONPATH:" in
    *":${VENDORED_DIR}:"*) : ;;
    *) export PYTHONPATH="${VENDORED_DIR}:${PYTHONPATH}" ;;
  esac
fi

echo "PYTHONPATH=${PYTHONPATH}"

# Quick non-fatal import checks (helpful in logs)
python - <<'PY'
import logging, sys
logging.basicConfig(level=logging.INFO)
logging.info("sys.path (first 8): %s", sys.path[:8])
for name in ("coinbase_advanced", "coinbase_advanced_py", "web.wsgi", "web"):
    try:
        __import__(name)
        logging.info("import OK: %s", name)
    except Exception as e:
        logging.info("import FAIL: %s -> %s", name, e)
PY

PORT="${PORT:-5000}"

# Exec gunicorn (so PID 1 is gunicorn)
exec gunicorn --config ./gunicorn.conf.py web.wsgi:app --bind "0.0.0.0:${PORT}"
