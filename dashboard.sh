#!/bin/bash
#
# NIJA Live Status Dashboard - Quick Launcher
# Provides convenient aliases for common monitoring tasks
#

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

show_usage() {
    cat << 'EOF'
╔══════════════════════════════════════════════════════════════════════════════╗
║                    NIJA Live Status Dashboard                                ║
║                         Quick Access Launcher                                ║
╚══════════════════════════════════════════════════════════════════════════════╝

USAGE:
  ./dashboard.sh [COMMAND]

COMMANDS:
  status          Show live status for all users (default)
  detailed        Show detailed status with extra info
  json            Output as JSON
  morning         Quick morning check (platform overview only)
  high-risk       Find users at high risk
  ready           List users ready to trade
  capital         Show total platform capital
  positions       Show users with open positions
  snapshot        Save current status snapshot
  help            Show this help message

EXAMPLES:
  ./dashboard.sh                    # Show status
  ./dashboard.sh morning            # Quick morning check
  ./dashboard.sh high-risk          # Find high-risk users
  ./dashboard.sh snapshot           # Save snapshot with timestamp

For full reference, see: OPERATORS_DASHBOARD_GUIDE.md

EOF
}

# Check if Python is available
if ! command -v python &> /dev/null && ! command -v python3 &> /dev/null; then
    echo -e "${RED}Error: Python not found${NC}"
    exit 1
fi

# Use python3 if available, otherwise python
PYTHON_CMD=$(command -v python3 || command -v python)

case "${1:-status}" in
    status)
        echo -e "${GREEN}📊 Loading live status...${NC}"
        $PYTHON_CMD user_status_summary.py
        ;;
    
    detailed)
        echo -e "${GREEN}📋 Loading detailed status...${NC}"
        $PYTHON_CMD user_status_summary.py --detailed
        ;;
    
    json)
        $PYTHON_CMD user_status_summary.py --json --quiet 2>/dev/null
        ;;
    
    morning|check)
        echo -e "${GREEN}☀️  Morning Platform Check${NC}"
        $PYTHON_CMD user_status_summary.py --quiet 2>&1 | grep "PLATFORM OVERVIEW" -A 5
        ;;
    
    high-risk|risk)
        echo -e "${YELLOW}🔍 Checking for high-risk users...${NC}"
        HIGH_RISK=$($PYTHON_CMD user_status_summary.py --json --quiet 2>/dev/null | jq -r '.users[] | select(.risk_level == "high") | .user_id')
        if [ -n "$HIGH_RISK" ]; then
            echo -e "${RED}⚠️  High risk users found:${NC}"
            echo "$HIGH_RISK"
        else
            echo -e "${GREEN}✅ No high-risk users${NC}"
        fi
        ;;
    
    ready|trading)
        echo -e "${GREEN}✅ Users ready to trade:${NC}"
        $PYTHON_CMD user_status_summary.py --json --quiet 2>/dev/null | \
            jq -r '.users[] | select(.can_trade == true) | "  • \(.user_id) (\(.tier)) - $\(.total_balance_usd)"'
        ;;
    
    capital|balance)
        CAPITAL=$($PYTHON_CMD user_status_summary.py --json --quiet 2>/dev/null | \
            jq -r '.platform_overview.total_capital_usd')
        echo -e "${GREEN}💰 Total Platform Capital: \$${CAPITAL}${NC}"
        ;;
    
    positions|trades)
        echo -e "${GREEN}📈 Users with open positions:${NC}"
        $PYTHON_CMD user_status_summary.py --json --quiet 2>/dev/null | \
            jq -r '.users[] | select(.open_positions > 0) | "  • \(.user_id): \(.open_positions) positions, P&L: $\(.unrealized_pnl)"'
        ;;
    
    snapshot|save)
        TIMESTAMP=$(date +%Y%m%d_%H%M%S)
        SNAPSHOT_FILE="snapshots/status_${TIMESTAMP}.json"
        mkdir -p snapshots
        $PYTHON_CMD user_status_summary.py --json --quiet 2>/dev/null > "$SNAPSHOT_FILE"
        echo -e "${GREEN}✅ Snapshot saved: ${SNAPSHOT_FILE}${NC}"
        ;;
    
    circuit|breaker)
        echo -e "${YELLOW}🚨 Checking circuit breakers...${NC}"
        BREAKERS=$($PYTHON_CMD user_status_summary.py --json --quiet 2>/dev/null | \
            jq -r '.users[] | select(.circuit_breaker == true) | .user_id')
        if [ -n "$BREAKERS" ]; then
            echo -e "${RED}⚠️  Circuit breakers active:${NC}"
            echo "$BREAKERS"
        else
            echo -e "${GREEN}✅ No circuit breakers active${NC}"
        fi
        ;;
    
    help|--help|-h)
        show_usage
        ;;
    
    *)
        echo -e "${RED}Unknown command: $1${NC}"
        echo ""
        show_usage
        exit 1
        ;;
esac
