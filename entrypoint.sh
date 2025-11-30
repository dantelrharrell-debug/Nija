#!/usr/bin/env bash
set -euo pipefail

echo "=== STARTING NIJA TRADING BOT CONTAINER ==="

# Safe PYTHONPATH defaults
PYTHONPATH="${PYTHONPATH:-}"
ROOT_DIR="/app"
VENDORED_DIR="${ROOT_DIR}/cd/vendor/coinbase_advanced_py"

# Ensure app root on PYTHONPATH
case ":$PYTHONPATH:" in
  *":${ROOT_DIR}:"*) : ;;
  *) PYTHONPATH="${ROOT_DIR}:${PYTHONPATH}" ;;
esac

# If vendored client exists, add it
if [ -d "$VENDORED_DIR" ]; then
  case ":$PYTHONPATH:" in
    *":${VENDORED_DIR}:"*) : ;;
    *) PYTHONPATH="${VENDORED_DIR}:${PYTHONPATH}" ;;
  esac
fi

export PYTHONPATH
echo "PYTHONPATH=${PYTHONPATH}"

# quick import diagnostic (non-fatal)
python - <<'PY'
import sys, logging
logging.basicConfig(level=logging.INFO)
logging.info("sys.path (first 8): %s", sys.path[:8])
for name in ("web.wsgi", "web", "app.wsgi", "app", "coinbase_advanced", "coinbase_advanced_py"):
    try:
        __import__(name)
        logging.info("imported: %s", name)
    except Exception as e:
        logging.info("failed import %s: %s", name, e)
PY

PORT="${PORT:-5000}"

# Exec Gunicorn with the module path that matches your structure (web.wsgi:app)
exec gunicorn --config ./gunicorn.conf.py web.wsgi:app --bind "0.0.0.0:${PORT}"
