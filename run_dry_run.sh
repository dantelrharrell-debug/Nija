#!/bin/bash
# 
# NIJA Dry-Run Mode Launcher
# 
# This script runs the bot in full dry-run (paper) mode with all exchanges enabled.
# Perfect for:
#   • Testing strategy logic safely
#   • Validating exchange configurations
#   • Reviewing startup banners
#   • Operator sign-off before going live
#
# NO REAL ORDERS will be placed. NO REAL MONEY at risk.
# All trading is simulated in-memory.
#
# Usage:
#   ./run_dry_run.sh [duration_minutes]
#
# Examples:
#   ./run_dry_run.sh           # Run continuously
#   ./run_dry_run.sh 30        # Run for 30 minutes then exit
#

set -e  # Exit on error

echo "╔══════════════════════════════════════════════════════════════════════════════╗"
echo "║                                                                              ║"
echo "║                  NIJA DRY-RUN MODE LAUNCHER                                  ║"
echo "║                                                                              ║"
echo "╚══════════════════════════════════════════════════════════════════════════════╝"
echo ""

# Parse duration argument
DURATION_MINUTES=${1:-0}

if [ "$DURATION_MINUTES" -gt 0 ]; then
    echo "📊 Mode: Dry-Run (Paper Trading)"
    echo "⏱️  Duration: ${DURATION_MINUTES} minutes"
else
    echo "📊 Mode: Dry-Run (Paper Trading)"
    echo "⏱️  Duration: Continuous (Ctrl+C to stop)"
fi
echo ""

# Set dry-run mode environment variables
export DRY_RUN_MODE=true
export PAPER_MODE=false
export LIVE_CAPITAL_VERIFIED=false

# Ensure we're not accidentally in live mode
if [ "${LIVE_CAPITAL_VERIFIED}" = "true" ]; then
    echo "❌ ERROR: LIVE_CAPITAL_VERIFIED is set to true"
    echo "   This conflicts with dry-run mode"
    echo "   Exiting for safety"
    exit 1
fi

echo "✅ Environment configured for dry-run:"
echo "   DRY_RUN_MODE=true"
echo "   PAPER_MODE=false"
echo "   LIVE_CAPITAL_VERIFIED=false"
echo ""

# Show which exchanges will be simulated
echo "📊 Exchanges that will be simulated:"
echo ""

if [ -n "${KRAKEN_PLATFORM_API_KEY}" ]; then
    echo "   ✅ Kraken (Platform) - SIMULATION MODE"
else
    echo "   ⚪ Kraken (Platform) - Not configured"
fi

if [ -n "${COINBASE_API_KEY}" ]; then
    echo "   ✅ Coinbase (Platform) - SIMULATION MODE"
else
    echo "   ⚪ Coinbase (Platform) - Not configured"
fi

if [ -n "${OKX_API_KEY}" ]; then
    echo "   ✅ OKX - SIMULATION MODE"
else
    echo "   ⚪ OKX - Not configured"
fi

if [ -n "${BINANCE_API_KEY}" ]; then
    echo "   ✅ Binance - SIMULATION MODE"
else
    echo "   ⚪ Binance - Not configured"
fi

if [ -n "${ALPACA_API_KEY}" ]; then
    echo "   ✅ Alpaca - SIMULATION MODE"
else
    echo "   ⚪ Alpaca - Not configured"
fi

echo ""
echo "⚠️  IMPORTANT: All configured exchanges will run in SIMULATION mode"
echo "⚠️  NO REAL ORDERS will be placed on ANY exchange"
echo ""

# Confirmation prompt
echo "╔══════════════════════════════════════════════════════════════════════════════╗"
echo "║  OPERATOR CONFIRMATION                                                       ║"
echo "╚══════════════════════════════════════════════════════════════════════════════╝"
echo ""
echo "This will start the bot in DRY-RUN mode (100% safe simulation)"
echo ""
read -p "Continue? (yes/no): " -r
echo ""

if [[ ! $REPLY =~ ^[Yy][Ee][Ss]$ ]]; then
    echo "❌ Aborted by operator"
    exit 0
fi

echo "✅ Starting dry-run mode..."
echo ""

# Start the bot with timeout if duration is set
if [ "$DURATION_MINUTES" -gt 0 ]; then
    TIMEOUT_SECONDS=$((DURATION_MINUTES * 60))
    echo "⏱️  Will run for ${DURATION_MINUTES} minutes (${TIMEOUT_SECONDS} seconds)"
    echo ""
    
    # Run with timeout
    timeout ${TIMEOUT_SECONDS}s bash start.sh || {
        exit_code=$?
        if [ $exit_code -eq 124 ]; then
            echo ""
            echo "╔══════════════════════════════════════════════════════════════════════════════╗"
            echo "║  DRY-RUN COMPLETED                                                           ║"
            echo "╚══════════════════════════════════════════════════════════════════════════════╝"
            echo ""
            echo "✅ Dry-run completed after ${DURATION_MINUTES} minutes"
            echo ""
            echo "📊 Next steps:"
            echo "   1. Review logs above for any errors or warnings"
            echo "   2. Verify all exchanges responded correctly"
            echo "   3. Check banner displays were clear"
            echo "   4. Review validation summary"
            echo ""
            echo "   If everything looks good, you can enable live trading:"
            echo "      export DRY_RUN_MODE=false"
            echo "      export LIVE_CAPITAL_VERIFIED=true"
            echo "      ./start.sh"
            echo ""
            exit 0
        else
            echo "❌ Bot exited with code: $exit_code"
            exit $exit_code
        fi
    }
else
    # Run continuously
    bash start.sh
fi
