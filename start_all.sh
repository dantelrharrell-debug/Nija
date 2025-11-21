#!/usr/bin/env bash
set -euo pipefail

echo "== START_ALL.SH: $(date -u) =="

# ---- Basic env checks (customize or remove as needed) ----
# If a required var is missing, we'll print a warning but continue.
missing=0
for var in COINBASE_API_KEY COINBASE_API_SECRET COINBASE_PEM_CONTENT; do
  if [ -z "${!var:-}" ]; then
    echo "❌ ERROR: ${var} not set"
    missing=1
  else
    echo "✅ ${var} present"
  fi
done

# If you want the script to abort on missing required envs, uncomment:
# if [ "$missing" -ne 0 ]; then
#   echo "Exiting due to missing env vars"
#   exit 1
# fi

# Optional: show PORT
echo "PORT = ${PORT:-5000}"

# Optional runtime-only installs (avoid in production)
# echo "Installing runtime extras..."
# python -m pip install --no-cache-dir -r /app/requirements.runtime.txt || true

# Ensure the app directory exists
cd /app || true

# Any pre-start commands you need (migrations, downloads, etc.)
# e.g. python manage.py migrate --noinput

# Start the app with gunicorn (adjust workers if desired)
exec gunicorn -w 1 -k sync -b 0.0.0.0:${PORT:-5000} main:app
