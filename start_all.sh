#!/usr/bin/env bash
set -euo pipefail

# start_all.sh - starts the nija trading loop in background and runs gunicorn

# allow overriding port via env
PORT="${PORT:-8080}"

# Ensure the script is executable (chmod +x start_all.sh in repo)
# Show .env notice:
if [ -f ".env" ]; then
  echo "$(date -u +'%Y-%m-%dT%H:%M:%SZ') | Loading .env from repo (be careful committing secrets!)"
  # optionally load it if you intend to during dev:
  # set -o allexport; source .env; set +o allexport
else
  echo "$(date -u +'%Y-%m-%dT%H:%M:%SZ') | .env not present — using environment variables provided by the host."
fi

echo "$(date -u +'%Y-%m-%dT%H:%M:%SZ') | Starting Nija trading bot (background loop)..."

# Set PYTHONPATH so vendor package can be imported
export PYTHONPATH="/app/vendor:${PYTHONPATH:-}"

# Launch trading bot in background and redirect its logs to stdout
# The bot itself will handle retries; we keep it supervised here to simplify container lifecycle.
nohup python3 nija_client.py 2>&1 &

# Start Gunicorn (wsgi app in web.wsgi:app).  Use sync/gthread as you prefer.
echo "$(date -u +'%Y-%m-%dT%H:%M:%SZ') | Starting Gunicorn web server..."
exec gunicorn -c gunicorn.conf.py web.wsgi:app
