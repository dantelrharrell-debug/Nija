#!/usr/bin/env bash
set -euo pipefail

# Export guard to ensure trading resumes at $10+
export MINIMUM_VIABLE_CAPITAL=${MINIMUM_VIABLE_CAPITAL:-10}

echo "MINIMUM_VIABLE_CAPITAL=${MINIMUM_VIABLE_CAPITAL}"

# Attempt liquidation (broad)
/workspaces/Nija/.venv/bin/python /workspaces/Nija/emergency_sell_all.py || true

# Targeted sells for stubborn holdings
/workspaces/Nija/.venv/bin/python /workspaces/Nija/scripts/sell_top_holdings.py || true

# Small wait for settlement
sleep 5

# Restart bot
bash /workspaces/Nija/start.sh || true

# Show recent status
sleep 3
 tail -50 /workspaces/Nija/nija_output.log | grep -E "balance|positions|concurrent|SIGNAL|TRADE BLOCKED|INSUFFICIENT" || true
