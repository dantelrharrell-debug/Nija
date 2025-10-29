#!/usr/bin/env bash
set -euo pipefail

# Ensure secrets dir exists and is secure
mkdir -p /opt/render/project/secrets
chmod 700 /opt/render/project/secrets

# Write Coinbase PEM from secret env var COINBASE_PEM_CONTENT (must be multiline)
if [ -z "${COINBASE_PEM_CONTENT:-}" ]; then
  echo "ERROR: COINBASE_PEM_CONTENT env var missing" >&2
  exit 1
fi

cat > /opt/render/project/secrets/coinbase.pem <<'PEM'
${COINBASE_PEM_CONTENT}
PEM

chmod 600 /opt/render/project/secrets/coinbase.pem
echo "Wrote PEM to /opt/render/project/secrets/coinbase.pem"

# Start the app with Gunicorn
export PORT=${PORT:-10000}
echo "Starting gunicorn on port $PORT"
exec gunicorn -b 0.0.0.0:$PORT nija_live_snapshot:app
