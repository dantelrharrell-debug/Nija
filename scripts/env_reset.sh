#!/usr/bin/env bash
set -euo pipefail

echo "Resetting Coinbase auth environment to Cloud API mode..."

# Unset PEM-related variables that force PEM/JWT mode
unset COINBASE_PEM_CONTENT || true
unset COINBASE_PEM_PATH || true

if [[ -z "${COINBASE_API_KEY:-}" || -z "${COINBASE_API_SECRET:-}" ]]; then
  echo "COINBASE_API_KEY or COINBASE_API_SECRET not set."
  echo "Enter Cloud API credentials from cloud.coinbase.com/access/api"
  read -r -p "API Key: " CB_KEY
  read -r -p "API Secret: " CB_SECRET
  export COINBASE_API_KEY="$CB_KEY"
  export COINBASE_API_SECRET="$CB_SECRET"
fi

echo "KEY chars:   $(echo -n "${COINBASE_API_KEY}" | wc -c)"
echo "SECRET chars: $(echo -n "${COINBASE_API_SECRET}" | wc -c)"

echo "Environment prepared. Test with:"
echo "  /workspaces/Nija/.venv/bin/python /workspaces/Nija/scripts/auth_sanity.py"
