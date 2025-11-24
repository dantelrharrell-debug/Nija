#!/usr/bin/env bash
set -euo pipefail

echo "=== STARTING NIJA TRADING BOT CONTAINER ==="

# =========================
# Configuration
# =========================
PORT=${PORT:-5000}
LOG_DIR=/app/logs
mkdir -p "$LOG_DIR"

# =========================
# Install dependencies (if needed)
# =========================
if [ -f requirements.txt ]; then
    echo "Installing Python dependencies..."
    pip install --upgrade pip setuptools wheel
    pip install -r requirements.txt
else
    echo "⚠️ requirements.txt not found, skipping pip install."
fi

# =========================
# Verify WSGI app exists
# =========================
WSGI_MODULE="web.wsgi:app"
echo "Checking WSGI module $WSGI_MODULE..."
python -c "import importlib; mod_name, app_name = '$WSGI_MODULE'.split(':'); mod = importlib.import_module(mod_name); getattr(mod, app_name)" || {
    echo "❌ WSGI module $WSGI_MODULE not found or 'app' missing."
    exit 1
}

# =========================
# Start background workers
# =========================
echo "[INFO] Starting background workers..."
nohup python3 /app/bots/tv_webhook_listener.py >> "$LOG_DIR/tv_webhook_listener.log" 2>&1 &
nohup python3 /app/bots/coinbase_trader.py >> "$LOG_DIR/coinbase_trader.log" 2>&1 &

# =========================
# Start web app (Gunicorn)
# =========================
echo "[INFO] Starting web app on port $PORT..."
exec gunicorn "$WSGI_MODULE" --bind 0.0.0.0:"$PORT" --log-level debug --error-logfile -
