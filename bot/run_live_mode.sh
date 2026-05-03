#!/bin/bash
# Run NIJA in LIVE Trading Mode (Real Money)

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

echo "💰 Starting NIJA in LIVE TRADING mode (REAL MONEY)"
echo "=================================================="
echo ""
echo "⚠️  WARNING: This will execute REAL trades on Coinbase"
echo "⚠️  Real money will be used"
echo ""
read -p "Type 'YES' to confirm: " confirmation

if [ "$confirmation" != "YES" ]; then
    echo "❌ Cancelled"
    exit 1
fi

export PAPER_MODE=false
export LIVE_CAPITAL_VERIFIED=true

exec "${REPO_ROOT}/start.sh" "$@"
