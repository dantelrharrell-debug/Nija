#!/bin/bash
set -euo pipefail

echo "=== STARTING NIJA TRADING BOT CONTAINER ==="

# -----------------------
# Install dependencies
# -----------------------
if [ -f requirements.txt ]; then
    echo "[INFO] Installing Python dependencies..."
    pip install --upgrade pip setuptools wheel
    pip install -r requirements.txt
else
    echo "[WARN] requirements.txt not found, skipping pip install."
fi

# -----------------------
# Verify WSGI app
# -----------------------
WSGI_MODULE="web.wsgi:app"
echo "[INFO] Checking WSGI module $WSGI_MODULE..."
python - <<'PY'
import importlib
import sys
import traceback

try:
    mod_name, app_name = '$WSGI_MODULE'.split(':')
    mod = importlib.import_module(mod_name)
    getattr(mod, app_name)
    print(f"{WSGI_MODULE} import ok")
except Exception:
    traceback.print_exc()
    sys.exit(1)
PY

# -----------------------
# Start background workers
# -----------------------
LOG_DIR=/app/logs
mkdir -p "$LOG_DIR"
echo "[INFO] Starting background bots..."
nohup python3 /app/bots/tv_webhook_listener.py >> "$LOG_DIR/tv_webhook_listener.log" 2>&1 &
nohup python3 /app/bots/coinbase_trader.py >> "$LOG_DIR/coinbase_trader.log" 2>&1 &

# -----------------------
# Start Gunicorn web app
# -----------------------
PORT=${PORT:-5000}
echo "[INFO] Starting Gunicorn on port $PORT..."
exec gunicorn "$WSGI_MODULE" \
    --bind 0.0.0.0:"$PORT" \
    --workers 1 \
    --threads 1 \
    --timeout 30 \
    --log-level debug \
    --error-logfile -
