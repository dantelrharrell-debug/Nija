#!/usr/bin/env bash
set -euo pipefail

# Load .env if it exists (optional)
if [ -f ".env" ]; then
  echo ".env found — loading"
  # shellcheck disable=SC1091
  . ./.env
else
  echo ".env not present — using environment variables provided by the host."
fi

# export PYTHONPATH to include vendor (so vendor.coinbase_advanced_py is importable)
export PYTHONPATH="/app/vendor:${PYTHONPATH:-}"

# log to stdout for container logs
echo "$(date -u +'%Y-%m-%dT%H:%M:%SZ') | Starting Nija trading bot (background loop)..."

# start the trading bot in background and redirect output to stdout/stderr
# It will continue running while gunicorn serves web.
# Using nohup + & so it survives (and logs appear in container logs).
nohup python -u /app/nija_client.py 2>&1 &

sleep 0.5

echo "$(date -u +'%Y-%m-%dT%H:%M:%SZ') | Starting Gunicorn web server..."
# Start gunicorn (replace web.wsgi:app if your wsgi module differs)
exec gunicorn -c /app/gunicorn.conf.py web.wsgi:app
