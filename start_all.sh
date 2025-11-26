#!/usr/bin/env bash
set -euo pipefail

echo "=== STARTING NIJA TRADING BOT CONTAINER ==="
date

WSGI_MODULE="${WSGI_MODULE:-web.wsgi:app}"
PORT="${PORT:-5000}"
LOG_DIR="/app/logs"
mkdir -p "$LOG_DIR"

echo "[INFO] WSGI_MODULE='$WSGI_MODULE'  PORT='$PORT'"

# Install deps if present
if [ -f "/app/requirements.txt" ]; then
  echo "[INFO] Installing Python dependencies..."
  pip install --upgrade pip setuptools wheel
  pip install -r /app/requirements.txt
fi

# Env checks
echo "[ENV] COINBASE_API_KEY set? ${COINBASE_API_KEY:+yes}"
echo "[ENV] COINBASE_API_SECRET set? ${COINBASE_API_SECRET:+yes}"
echo "[ENV] COINBASE_API_SUB set? ${COINBASE_API_SUB:+yes}"

# WSGI module verification + Coinbase import test
python - <<PY
import importlib, os, traceback

WSGI = os.environ.get("WSGI_MODULE", "$WSGI_MODULE")
print(f"[PY] verifying WSGI module: {WSGI!r}")

try:
    mod_name, app_name = WSGI.split(":", 1)
    mod = importlib.import_module(mod_name)
    app = getattr(mod, app_name)
    print(f"[PY] SUCCESS: imported {mod_name}.{app_name} -> type={type(app)}")
except Exception:
    print("[PY][ERROR] Failed to import WSGI module. Traceback follows:")
    traceback.print_exc()
    raise SystemExit(1)

# Coinbase client test
coinbase_import_paths = [
    "coinbase_advanced.client",
    "coinbase_advanced_py.client",
    "coinbase_advanced_py",
    "coinbase_advanced",
]
found = False
for p in coinbase_import_paths:
    try:
        importlib.import_module(p)
        print(f"[PY] Found importable module: {p}")
        found = True
        break
    except Exception:
        pass
if not found:
    print("[PY][WARN] No Coinbase client importable. Check coinbase-advanced-py installation.")
PY

# Start background workers
for worker in tv_webhook_listener coinbase_trader; do
  nohup python -m "bots.$worker" >> "$LOG_DIR/$worker.log" 2>&1 &
done

sleep 0.5
echo "[INFO] Background workers started (logs -> $LOG_DIR)."

# Start Gunicorn
echo "[INFO] Launching Gunicorn on 0.0.0.0:$PORT..."
exec gunicorn "$WSGI_MODULE" --bind "0.0.0.0:$PORT" --workers 1 --threads 1 --timeout 30 --log-level debug --error-logfile -
