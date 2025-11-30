#!/usr/bin/env bash
# entrypoint.sh - robust startup for NIJA Trading Bot
set -euo pipefail

echo "=== STARTING NIJA TRADING BOT CONTAINER ==="

# Safe default for PYTHONPATH (avoid unbound variable when set -u is used)
PYTHONPATH="${PYTHONPATH:-}"

# App root and vendored client path
ROOT_DIR="/app"
VENDORED_DIR="${ROOT_DIR}/cd/vendor/coinbase_advanced_py"

# Prepend app root and vendor folder to PYTHONPATH if not already present
case ":$PYTHONPATH:" in
  *":${ROOT_DIR}:"*) : ;; 
  *) PYTHONPATH="${ROOT_DIR}:${PYTHONPATH}" ;;
esac

if [ -d "$VENDORED_DIR" ]; then
  case ":$PYTHONPATH:" in
    *":${VENDORED_DIR}:"*) : ;;
    *) PYTHONPATH="${VENDORED_DIR}:${PYTHONPATH}" ;;
  esac
fi

export PYTHONPATH
echo "PYTHONPATH=${PYTHONPATH}"

# Quick non-fatal python import check (prints to logs)
python - <<'PY'
import sys, logging
logging.basicConfig(level=logging.INFO)
logging.info("sys.path preview: %s", sys.path[:6])
found = False
for name in ("coinbase_advanced", "coinbase_advanced_py"):
    try:
        __import__(name)
        logging.info("Imported vendored package: %s", name)
        found = True
        break
    except Exception as e:
        logging.info("Couldn't import %s: %s", name, e)
if not found:
    logging.warning("Vendored coinbase client not importable. Live trading disabled.")
PY

# Determine PORT (platform-provided or fallback)
PORT="${PORT:-5000}"

# Run gunicorn - use exec so it becomes PID 1
exec gunicorn --config ./gunicorn.conf.py web.wsgi:app --bind "0.0.0.0:${PORT}"
