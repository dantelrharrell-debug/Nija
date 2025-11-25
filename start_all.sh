#!/bin/bash
set -euo pipefail

echo "=== STARTING NIJA TRADING BOT CONTAINER ==="

# Install dependencies
if [ -f requirements.txt ]; then
    echo "[INFO] Installing Python dependencies..."
    pip install --upgrade pip setuptools wheel
    pip install -r requirements.txt
fi

# Verify WSGI app
WSGI_MODULE="web.wsgi:app"
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

# Start background workers
LOG_DIR=/app/logs
mkdir -p "$LOG_DIR"
nohup python3 /app/bots/tv_webhook_listener.py >> "$LOG_DIR/tv_webhook_listener.log" 2>&1 &
nohup python3 /app/bots/coinbase_trader.py >> "$LOG_DIR/coinbase_trader.log" 2>&1 &

# Start Gunicorn
PORT=${PORT:-5000}
exec gunicorn "$WSGI_MODULE" --bind 0.0.0.0:"$PORT" --workers 1 --threads 1 --timeout 30 --log-level debug --error-logfile -
