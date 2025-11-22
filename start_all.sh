#!/usr/bin/env sh
set -eu
# start_all.sh - minimal, safe startup wrapper for Nija bot

echo "== START_ALL.SH: $(date -u) =="
# Print environment markers for easier debugging
echo "✅ COINBASE_API_KEY present: ${COINBASE_API_KEY:+YES}"
echo "✅ COINBASE_API_SECRET present: ${COINBASE_API_SECRET:+YES}"
echo "✅ COINBASE_PEM_CONTENT present: ${COINBASE_PEM_CONTENT:+YES}"
echo "PORT = ${PORT:-5000}"

# Optional: run any env checks or migrations here
# e.g. python scripts/check_env.py

# Start the app with gunicorn (fallback if start script not present)
exec sh -c "gunicorn -w 1 -k sync -b 0.0.0.0:${PORT:-5000} main:app"
