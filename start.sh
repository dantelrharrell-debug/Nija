#!/usr/bin/env bash
set -euo pipefail

# Ensure secrets dir exists
mkdir -p /opt/render/project/secrets
chmod 700 /opt/render/project/secrets

# Write Coinbase PEM from a Render secret env var COINBASE_PEM_CONTENT
# NOTE: set COINBASE_PEM_CONTENT in Render's dashboard as the full PEM (including BEGIN/END lines)
if [ -z "${COINBASE_PEM_CONTENT:-}" ]; then
  echo "ERROR: COINBASE_PEM_CONTENT env var missing" >&2
  exit 1
fi

cat > /opt/render/project/secrets/coinbase.pem <<'PEM'
${COINBASE_PEM_CONTENT}
PEM

chmod 600 /opt/render/project/secrets/coinbase.pem

# Start the app
export PORT=${PORT:-10000}
gunicorn -b 0.0.0.0:$PORT nija_live_snapshot:app
