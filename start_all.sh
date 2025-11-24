#!/usr/bin/env bash
set -euo pipefail

# set Gunicorn debug logging
export GUNICORN_CMD_ARGS="--log-level debug --error-logfile -"

# start background workers
python tv_webhook_listener.py  >> /app/logs/tv_webhook_listener.py.log 2>&1 &
python coinbase_trader.py     >> /app/logs/coinbase_trader.py.log 2>&1 &

# run web in foreground
exec gunicorn web:app --bind 0.0.0.0:${PORT:-5000}
