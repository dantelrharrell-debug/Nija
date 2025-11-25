#!/usr/bin/env bash
set -euo pipefail

# ====== START ======
echo "=== STARTING NIJA TRADING BOT CONTAINER ==="
date

# --------
# Config
# --------
WSGI_MODULE="${WSGI_MODULE:-web.wsgi:app}"
PORT="${PORT:-5000}"
LOG_DIR="/app/logs"
mkdir -p "$LOG_DIR"

echo "[INFO] WSGI_MODULE='$WSGI_MODULE'  PORT='$PORT'"

# --------
# (Optional) install deps if requirements.txt present
# You can comment this out if you prebuilt deps into the image.
# --------
if [ -f "/app/requirements.txt" ]; then
  echo "[INFO] Installing Python dependencies from /app/requirements.txt..."
  pip install --upgrade pip setuptools wheel
  pip install -r /app/requirements.txt
else
  echo "[INFO] No requirements.txt found at /app/requirements.txt - assuming deps baked in image."
fi

# --------
# Quick env debug (will not print secrets fully)
# --------
echo "[ENV] COINBASE_API_KEY set? ${COINBASE_API_KEY:+yes}"
echo "[ENV] COINBASE_API_SECRET set? ${COINBASE_API_SECRET:+yes}"
echo "[ENV] COINBASE_API_SUB set? ${COINBASE_API_SUB:+yes}"

# --------
# Python-level checks (expands $WSGI_MODULE correctly)
# --------
python - <<PY
import importlib, os, sys, traceback

WSGI = os.environ.get("WSGI_MODULE", "$WSGI_MODULE")
print(f"[PY] verifying WSGI module: {WSGI!r}")

try:
    mod_name, app_name = WSGI.split(":", 1)
except Exception as e:
    print("[PY][ERROR] WSGI_MODULE must be in form 'module.submodule:appname' (found: {!r})".format(WSGI))
    raise SystemExit(1)

try:
    mod = importlib.import_module(mod_name)
    app = getattr(mod, app_name)
    print(f"[PY] SUCCESS: imported {mod_name}.{app_name} -> type={type(app)}")
except Exception:
    print("[PY][ERROR] Failed to import WSGI module. Traceback follows:")
    traceback.print_exc()
    raise SystemExit(1)

# Coinbase client basic import test
print("[PY] Checking installed Coinbase client library...")
coinbase_import_paths = [
    "coinbase_advanced.client",        # some packages expose coinbase_advanced
    "coinbase_advanced_py.client",     # other variants
    "coinbase_advanced_py",            # fallback
    "coinbase_advanced",               # fallback
]
found = False
for p in coinbase_import_paths:
    try:
        m = importlib.import_module(p)
        print(f"[PY] Found importable module: {p}")
        found = True
        break
    except Exception:
        pass

if not found:
    print("[PY][WARN] No Coinbase client importable from expected names:", coinbase_import_paths)
else:
    print("[PY] Coinbase client import check passed (module: {})".format(p))

# Check Coinbase env keys presence (do not print values)
required = ["COINBASE_API_KEY", "COINBASE_API_SECRET", "COINBASE_API_SUB"]
missing = [k for k in required if not os.getenv(k)]
if missing:
    print("[PY][WARN] Missing Coinbase environment keys:", missing)
else:
    print("[PY] All Coinbase env keys present (not printing values).")

PY

# --------
# Start background workers safely (so failures just log)
# --------
echo "[INFO] Starting background workers (logs -> $LOG_DIR)..."

# tv_webhook_listener: run inside safe python wrapper to catch errors
nohup python - <<PY >> "$LOG_DIR/tv_webhook_listener.log" 2>&1 &
import traceback
try:
    # adjust import path to your module location
    from bots.tv_webhook_listener import main as _tv_main
    print("[BG] tv_webhook_listener starting")
    _tv_main()
except Exception:
    print("[BG][ERROR] tv_webhook_listener crashed:")
    traceback.print_exc()
PY

# coinbase_trader: same safe wrapper
nohup python - <<PY >> "$LOG_DIR/coinbase_trader.log" 2>&1 &
import traceback
try:
    from bots.coinbase_trader import main as _cb_main
    print("[BG] coinbase_trader starting")
    _cb_main()
except Exception:
    print("[BG][ERROR] coinbase_trader crashed:")
    traceback.print_exc()
PY

sleep 0.5
echo "[INFO] Background workers started (if they didn't crash). Check logs in $LOG_DIR."

# --------
# Finally run Gunicorn (replace only when WSGI checks passed)
# --------
echo "[INFO] Launching Gunicorn with $WSGI_MODULE on 0.0.0.0:$PORT..."
exec gunicorn "$WSGI_MODULE" --bind "0.0.0.0:$PORT" --workers 1 --threads 1 --timeout 30 --log-level debug --error-logfile -
