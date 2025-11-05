#!/bin/bash
# setup_nija_env.sh
# Sets environment variables for Nija trading bot in Codespaces

# Coinbase API credentials
export COINBASE_API_KEY="organizations/ce77e4ea-ecca-42ec-912a-b6b4455ab9d0/apiKeys/d3c4f66b-809e-4ce4-9d6c-1a8d31b777d5"

# Use single quotes and replace literal \n with actual newlines
export COINBASE_API_SECRET=$(echo '-----BEGIN EC PRIVATE KEY-----
MHcCAQEEIB7MOrFbx1Kfc/DxXZZ3Gz4Y2hVY9SbcfUHPiuQmLSPxoAoGCCqGSM49
AwEHoUQDQgAEiFR+zABGG0DB0HFgjo69cg3tY1Wt41T1gtQp3xrMnvWwio96ifmk
Ah1eXfBIuinsVEJya4G9DZ01hzaF/edTIw==
-----END EC PRIVATE KEY-----')

export COINBASE_API_PASSPHRASE=""
export COINBASE_API_BASE="https://api.coinbase.com"

# Confirm variables are set (mask sensitive info)
echo "✅ Environment variables set:"
echo "COINBASE_API_KEY: ${COINBASE_API_KEY:0:6}... (masked)"
echo "COINBASE_API_SECRET: set (masked)"
echo "COINBASE_API_PASSPHRASE: ${COINBASE_API_PASSPHRASE}"
echo "COINBASE_API_BASE: ${COINBASE_API_BASE}"
