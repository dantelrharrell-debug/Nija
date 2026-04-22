#!/bin/bash
set -e  # Exit on error

echo "=============================="
echo "    STARTING NIJA TRADING BOT"
echo "=============================="

# ── Single-instance guard ────────────────────────────────────────────────────
# Find and kill any pre-existing NIJA bot.py processes so that only ONE
# instance ever runs.  This mirrors the manual steps:
#   ps aux | grep bot.py
#   kill -9 <PID>
# Set SKIP_KILL_EXISTING=true to bypass (e.g. during automated test harnesses).
if [ "${SKIP_KILL_EXISTING:-false}" != "true" ]; then
    _SELF_PID=$$
    # Collect PIDs matching "bot.py" that are NOT this shell.
    _DUP_PIDS=$(pgrep -f "python[0-9.]*.*bot\.py" 2>/dev/null | grep -v "^${_SELF_PID}$" || true)
    if [ -n "$_DUP_PIDS" ]; then
        echo ""
        echo "⚠️  Duplicate NIJA process(es) detected — killing before start:"
        for _pid in $_DUP_PIDS; do
            echo "   Killing PID $_pid …"
            kill -9 "$_pid" 2>/dev/null || true
        done
        # Brief pause to let the OS clean up the killed processes.
        sleep 1
        echo "✅ Duplicate instance(s) removed."
        echo ""
    fi
    # Remove a stale PID file so the new instance can acquire the lock cleanly.
    _PID_FILE="data/nija.pid"
    if [ -f "$_PID_FILE" ]; then
        _OLD_PID=$(head -n 1 "$_PID_FILE" 2>/dev/null || echo "")
        if [ -n "$_OLD_PID" ] && ! kill -0 "$_OLD_PID" 2>/dev/null; then
            echo "🗑️  Removing stale PID file (PID $_OLD_PID no longer running)."
            rm -f "$_PID_FILE"
        fi
    fi
fi
# ────────────────────────────────────────────────────────────────────────────

# Parse command line arguments
WAIT_FOR_CONFIG="${WAIT_FOR_CONFIG:-false}"  # Default from environment
for arg in "$@"; do
    case $arg in
        --wait-for-config)
            WAIT_FOR_CONFIG="true"
            shift
            ;;
    esac
done

# Show wait-for-config mode status
if [ "$WAIT_FOR_CONFIG" = "true" ]; then
    echo "⏸️  Wait-for-config mode: ENABLED"
    echo ""
    echo "   Health endpoint will report one of three states:"
    echo "   • BLOCKED (503) - Missing config, waiting for credentials"
    echo "   • READY   (200) - Config complete, bot operational"
    echo "   • ERROR   (500) - Hard error detected, needs intervention"
    echo ""
    echo "   This prevents restart loops while providing clear status signals."
else
    echo "📋 Wait-for-config mode: DISABLED (use --wait-for-config or set WAIT_FOR_CONFIG=true)"
    echo "   If config is missing, container will exit with code 0"
fi
echo ""

# Helper function to exit gracefully for configuration errors
exit_config_error() {
    echo ""
    if [ "$WAIT_FOR_CONFIG" = "true" ]; then
        echo "⏸️  Configuration incomplete - entering wait mode"
        echo ""
        echo "   🎯 This prevents restart loops while waiting for configuration"
        echo ""
        echo "   Health endpoint will report:"
        echo "   • Status: BLOCKED (HTTP 503)"
        echo "   • State:  awaiting_configuration"
        echo "   • Action: Set credentials and restart"
        echo ""
        echo "   Query the health endpoint:"
        echo "     curl http://localhost:\${PORT:-8080}/healthz"
        echo ""
        echo "   Expected response:"
        echo "     {"
        echo "       \"status\": \"blocked\","
        echo "       \"state\": \"awaiting_configuration\","
        echo "       \"message\": \"Waiting for configuration\","
        echo "       \"required\": {"
        echo "         \"KRAKEN_PLATFORM_API_KEY\": \"Kraken API key (required)\","
        echo "         \"KRAKEN_PLATFORM_API_SECRET\": \"Kraken API secret (required)\""
        echo "       }"
        echo "     }"
        echo ""
        echo "   Once configured, restart and health will return:"
        echo "     {\"status\": \"ready\", \"state\": \"configured\"} (HTTP 200)"
        echo ""
        # Start health server in wait mode and keep container running
        echo "🌐 Starting config-aware health server..."
        $PY -u config_health_server.py
        # If health server exits, exit with 0 to prevent restart loop
        exit 0
    else
        echo "⚠️  Configuration error - exiting without restart (exit code 0)"
        echo "    The container will not restart automatically."
        echo "    Please configure credentials and manually restart the deployment."
        echo ""
        exit 0
    fi
}

# Prefer workspace venv Python, fallback to system python3
PY=""
if [ -x ./.venv/bin/python ]; then
    PY="./.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PY="$(command -v python3)"
fi

if [ -z "$PY" ]; then
    echo "❌ No Python interpreter found (venv or system)"
    echo "   Ensure .venv exists or install python3"
    exit 127
fi

$PY --version 2>&1

# Ensure Python version output is flushed
sleep 0.05

# Test Coinbase module (OPTIONAL - secondary broker)
$PY -c "from coinbase.rest import RESTClient; print('✅ Coinbase REST client available')" 2>&1 || {
    echo "⚠️  Coinbase REST client not available (this is OK - Coinbase is the secondary broker)"
}

# Ensure output is flushed
sleep 0.05

# Test Kraken module (REQUIRED - Kraken is PRIMARY broker)
# CRITICAL: Kraken Platform credentials MUST be set
if [ -n "${KRAKEN_PLATFORM_API_KEY}" ] && [ -n "${KRAKEN_PLATFORM_API_SECRET}" ]; then
    $PY -c "import krakenex; import pykrakenapi; print('✅ Kraken SDK (krakenex + pykrakenapi) available')" 2>&1 || {
        echo ""
        echo "❌ CRITICAL: Kraken Master credentials are set but Kraken SDK is NOT installed"
        echo ""
        echo "The Kraken SDK (krakenex + pykrakenapi) is required when Kraken credentials are configured."
        echo ""
        echo "🔧 SOLUTION:"
        echo "   1. Verify railway.json uses 'builder': 'DOCKERFILE' (not NIXPACKS)"
        echo "   2. Trigger a fresh deployment (not just restart):"
        echo "      Railway: Settings → 'Redeploy'"
        echo "      Render: Manual Deploy → 'Clear build cache & deploy'"
        echo ""
        echo "   The Dockerfile includes explicit installation of krakenex and pykrakenapi."
        echo "   If using NIXPACKS/Railway buildpack instead of Docker, the installation may fail silently."
        echo ""
        echo "📖 See SOLUTION_KRAKEN_LIBRARY_NOT_INSTALLED.md for detailed troubleshooting"
        echo ""
        exit_config_error
    }
else
    # CRITICAL: Kraken credentials are REQUIRED as primary broker
    echo ""
    echo "❌ CRITICAL: Kraken Platform credentials are REQUIRED"
    echo ""
    echo "Kraken is the primary broker."
    echo "You MUST configure Kraken credentials to use this bot."
    echo ""
    echo "🔧 SOLUTION:"
    echo "   1. Get API credentials from https://www.kraken.com/u/security/api"
    echo "   2. Set environment variables:"
    echo "      export KRAKEN_PLATFORM_API_KEY='<your-api-key>'"
    echo "      export KRAKEN_PLATFORM_API_SECRET='<your-api-secret>'"
    echo "   3. Restart the bot"
    echo ""
    echo "📖 See .env.example for detailed setup instructions"
    echo ""
    exit_config_error
fi

# Ensure all Python test output is flushed before continuing
sleep 0.05

# Source build-time git metadata written by inject_git_metadata.sh (Docker build)
# This makes GIT_BRANCH / GIT_COMMIT / GIT_COMMIT_SHORT available when the image
# was built with proper --build-arg values (e.g. via railway.json buildArgs).
if [ -f ".env.build" ]; then
    . .env.build
fi

BRANCH_VAL=${GIT_BRANCH}
COMMIT_VAL=${GIT_COMMIT_SHORT:-${GIT_COMMIT}}

# Populate branch/commit from git if not provided
if ([ -z "$BRANCH_VAL" ] || [ "$BRANCH_VAL" = "unknown" ]) && command -v git >/dev/null 2>&1; then
    BRANCH_VAL=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")
fi
if ([ -z "$COMMIT_VAL" ] || [ "$COMMIT_VAL" = "unknown" ]) && command -v git >/dev/null 2>&1; then
    COMMIT_VAL=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
fi

# Fallback: use Railway-provided runtime environment variables (always available in Railway deployments)
if ([ -z "$BRANCH_VAL" ] || [ "$BRANCH_VAL" = "unknown" ]) && [ -n "$RAILWAY_GIT_BRANCH" ]; then
    BRANCH_VAL="$RAILWAY_GIT_BRANCH"
fi
if ([ -z "$COMMIT_VAL" ] || [ "$COMMIT_VAL" = "unknown" ]) && [ -n "$RAILWAY_GIT_COMMIT_SHA" ]; then
    COMMIT_VAL="${RAILWAY_GIT_COMMIT_SHA:0:7}"
fi

echo "Branch: ${BRANCH_VAL:-unknown}"
echo "Commit: ${COMMIT_VAL:-unknown}"

# RISK CHECK: Warn if git metadata is unknown
if [ "${BRANCH_VAL:-unknown}" = "unknown" ] || [ "${COMMIT_VAL:-unknown}" = "unknown" ]; then
    echo ""
    echo "⚠️  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "⚠️  RISK: Running with UNKNOWN git metadata"
    echo "⚠️  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "⚠️  Cannot verify which code version is running!"
    echo "⚠️  Branch: ${BRANCH_VAL:-unknown}"
    echo "⚠️  Commit: ${COMMIT_VAL:-unknown}"
    echo "⚠️  "
    echo "⚠️  This is DANGEROUS in production - you cannot trace issues to code."
    echo "⚠️  "
    echo "⚠️  RECOMMENDED: Set GIT_BRANCH and GIT_COMMIT in your deployment:"
    echo "⚠️    export GIT_BRANCH=\$(git rev-parse --abbrev-ref HEAD)"
    echo "⚠️    export GIT_COMMIT=\$(git rev-parse --short HEAD)"
    echo "⚠️  "
    echo "⚠️  Or use inject_git_metadata.sh during build process."
    echo "⚠️  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo ""
fi

# Ensure git info output is flushed
sleep 0.05

# Explicitly allow counting Consumer USD unless overridden
export ALLOW_CONSUMER_USD="${ALLOW_CONSUMER_USD:-true}"
echo "ALLOW_CONSUMER_USD=${ALLOW_CONSUMER_USD}"

# Load environment from .env if present (so bot can run live without manual exports)
if [ -f ./.env ]; then
    echo ""
    echo "🧩 Loading environment variables from .env"
    set -a
    . ./.env
    set +a
fi

# Debug: Show credential status for ALL exchanges
echo ""
echo "🔍 EXCHANGE CREDENTIAL STATUS:"
echo "   ────────────────────────────────────────────────────────"

# Kraken - Platform (PRIMARY BROKER)
echo "   📊 KRAKEN (Platform) - PRIMARY BROKER:"
if [ -n "${KRAKEN_PLATFORM_API_KEY}" ] && [ -n "${KRAKEN_PLATFORM_API_SECRET}" ]; then
    echo "      ✅ Configured (Key: ${#KRAKEN_PLATFORM_API_KEY} chars, Secret: ${#KRAKEN_PLATFORM_API_SECRET} chars)"
else
    echo "      ❌ Not configured (REQUIRED)"
fi

# Coinbase - Platform (SECONDARY BROKER)
echo "   📊 COINBASE (Platform) - SECONDARY BROKER:"
if [ -n "${COINBASE_API_KEY}" ] && [ -n "${COINBASE_API_SECRET}" ]; then
    echo "      ✅ Configured (Key: ${#COINBASE_API_KEY} chars, Secret: ${#COINBASE_API_SECRET} chars)"
else
    echo "      ⚠️  Not configured (optional secondary broker)"
fi

# Kraken - User #1 (Daivon)
echo "   👤 KRAKEN (User #1: Daivon):"
if [ -n "${KRAKEN_USER_DAIVON_API_KEY}" ] && [ -n "${KRAKEN_USER_DAIVON_API_SECRET}" ]; then
    echo "      ✅ Configured (Key: ${#KRAKEN_USER_DAIVON_API_KEY} chars, Secret: ${#KRAKEN_USER_DAIVON_API_SECRET} chars)"
else
    echo "      ❌ Not configured"
fi

# Kraken - User #2 (Tania)
echo "   👤 KRAKEN (User #2: Tania):"
if [ -n "${KRAKEN_USER_TANIA_API_KEY}" ] && [ -n "${KRAKEN_USER_TANIA_API_SECRET}" ]; then
    echo "      ✅ Configured (Key: ${#KRAKEN_USER_TANIA_API_KEY} chars, Secret: ${#KRAKEN_USER_TANIA_API_SECRET} chars)"
else
    echo "      ❌ Not configured"
fi

# OKX
echo "   📊 OKX (Master):"
if [ -n "${OKX_API_KEY}" ] && [ -n "${OKX_API_SECRET}" ] && [ -n "${OKX_PASSPHRASE}" ]; then
    echo "      ✅ Configured (Key: ${#OKX_API_KEY} chars, Secret: ${#OKX_API_SECRET} chars)"
else
    echo "      ❌ Not configured"
fi

# Binance
echo "   📊 BINANCE (Master):"
if [ -n "${BINANCE_API_KEY}" ] && [ -n "${BINANCE_API_SECRET}" ]; then
    echo "      ✅ Configured (Key: ${#BINANCE_API_KEY} chars, Secret: ${#BINANCE_API_SECRET} chars)"
else
    echo "      ❌ Not configured"
fi

# Alpaca - Master
echo "   📊 ALPACA (Master):"
if [ -n "${ALPACA_API_KEY}" ] && [ -n "${ALPACA_API_SECRET}" ]; then
    echo "      ✅ Configured (Key: ${#ALPACA_API_KEY} chars, Secret: ${#ALPACA_API_SECRET} chars, Paper: ${ALPACA_PAPER:-true})"
else
    echo "      ❌ Not configured"
fi

# Alpaca - User #2 (Tania)
echo "   👤 ALPACA (User #2: Tania):"
if [ -n "${ALPACA_USER_TANIA_API_KEY}" ] && [ -n "${ALPACA_USER_TANIA_API_SECRET}" ]; then
    echo "      ✅ Configured (Key: ${#ALPACA_USER_TANIA_API_KEY} chars, Secret: ${#ALPACA_USER_TANIA_API_SECRET} chars, Paper: ${ALPACA_USER_TANIA_PAPER:-true})"
else
    echo "      ❌ Not configured"
fi

echo "   ────────────────────────────────────────────────────────"
echo ""
echo "🔧 Trading Guards:"
echo "   MIN_CASH_TO_BUY=${MIN_CASH_TO_BUY:-5.0}"
echo "   MINIMUM_TRADING_BALANCE=${MINIMUM_TRADING_BALANCE:-25.0}"
echo ""

# ═══════════════════════════════════════════════════════════════════════
# CRITICAL: Trading Mode Verification (Testing vs. Live)
# ═══════════════════════════════════════════════════════════════════════
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🎯 TRADING MODE VERIFICATION"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Helper function to check if value is truthy (true, 1, yes)
is_truthy() {
    local val="${1:-false}"
    [ "$val" = "true" ] || [ "$val" = "1" ] || [ "$val" = "yes" ]
}

# Check mode flags (DRY_RUN takes highest priority)
DRY_RUN_MODE_VAL="${DRY_RUN_MODE:-false}"
PAPER_MODE_VAL="${PAPER_MODE:-false}"
LIVE_CAPITAL_VERIFIED_VAL="${LIVE_CAPITAL_VERIFIED:-false}"

echo "   DRY_RUN_MODE: ${DRY_RUN_MODE_VAL}"
echo "   PAPER_MODE: ${PAPER_MODE_VAL}"
echo "   LIVE_CAPITAL_VERIFIED: ${LIVE_CAPITAL_VERIFIED_VAL}"
echo ""

# Determine actual mode and warn accordingly (DRY_RUN > LIVE > PAPER)
if is_truthy "${DRY_RUN_MODE_VAL}"; then
    echo "   🟡 MODE: DRY RUN (FULL SIMULATION)"
    echo "   ✅ SAFEST MODE - No real orders on any exchange"
    echo "   ✅ All exchanges in simulation mode"
    echo "   ✅ No real money at risk"
    echo "   ✅ All trading is simulated in-memory"
    echo ""
    echo "   This mode is perfect for:"
    echo "      • Testing strategy logic"
    echo "      • Validating exchange configurations"
    echo "      • Reviewing startup banners and validation"
    echo "      • Operator sign-off before going live"
    echo ""
    echo "   To enable live trading after validation:"
    echo "      export DRY_RUN_MODE=false"
    echo "      export LIVE_CAPITAL_VERIFIED=true"
    echo ""
    echo "   ℹ️  Multi-exchange trading: verify credentials for each exchange you want:"
    echo "      KRAKEN_PLATFORM_API_KEY / KRAKEN_PLATFORM_API_SECRET  (primary broker)"
    echo "      OKX_API_KEY / OKX_API_SECRET / OKX_PASSPHRASE         (optional)"
    echo "      BINANCE_API_KEY / BINANCE_API_SECRET                  (optional)"
    echo "      ALPACA_API_KEY / ALPACA_API_SECRET                    (optional)"
elif is_truthy "${LIVE_CAPITAL_VERIFIED_VAL}"; then
    echo "   🔴 MODE: LIVE TRADING"
    echo "   ⚠️  REAL MONEY AT RISK"
    echo "   ⚠️  This bot will execute real trades with real capital"
    echo "   ⚠️  Ensure this is INTENTIONAL"
    echo ""
    echo "   To disable live trading:"
    echo "      export LIVE_CAPITAL_VERIFIED=false"
    echo ""
    echo "   To test safely first:"
    echo "      export DRY_RUN_MODE=true"
elif is_truthy "${PAPER_MODE_VAL}"; then
    echo "   📝 MODE: PAPER TRADING"
    echo "   ℹ️  Simulated trading only, no real money"
else
    echo "   ⚠️  MODE: UNCLEAR"
    echo "   ⚠️  No mode flags explicitly set"
    echo "   ⚠️  Bot behavior may be unpredictable"
    echo ""
    echo "   Recommended: Set one of the following:"
    echo "      export DRY_RUN_MODE=true           # For full simulation (safest)"
    echo "      export PAPER_MODE=true             # For paper trading"
    echo "      export LIVE_CAPITAL_VERIFIED=true  # For live trading (use with caution)"
fi

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# ═══════════════════════════════════════════════════════════════════════
# GUARD 1: Block live trading when git metadata is unknown
# Untraceable code cannot be audited or safely rolled back.
# ═══════════════════════════════════════════════════════════════════════
if is_truthy "${LIVE_CAPITAL_VERIFIED_VAL}" && ! is_truthy "${DRY_RUN_MODE_VAL}"; then
    if [ "${BRANCH_VAL:-unknown}" = "unknown" ] || [ "${COMMIT_VAL:-unknown}" = "unknown" ]; then
        if ! is_truthy "${ALLOW_UNTRACEABLE_CODE:-false}"; then
            echo ""
            echo "❌ BLOCKED: Live trading requires traceable git metadata."
            echo "   Branch: ${BRANCH_VAL:-unknown}  Commit: ${COMMIT_VAL:-unknown}"
            echo ""
            echo "   Options:"
            echo "     1. Set git metadata:     bash inject_git_metadata.sh"
            echo "     2. Test safely first:    export DRY_RUN_MODE=true"
            echo "     3. Override (emergency): export ALLOW_UNTRACEABLE_CODE=true"
            echo ""
            exit 1
        fi
        echo "⚠️  WARNING: ALLOW_UNTRACEABLE_CODE=true — git metadata check bypassed"
    fi
fi

# ═══════════════════════════════════════════════════════════════════════
# GUARD 2: Confirm that live trading is intentional
# ═══════════════════════════════════════════════════════════════════════
if is_truthy "${LIVE_CAPITAL_VERIFIED_VAL}" && ! is_truthy "${DRY_RUN_MODE_VAL}"; then
    if is_truthy "${LIVE_TRADING_CONFIRMED:-false}"; then
        echo "✅ Live trading confirmed (LIVE_TRADING_CONFIRMED=true)"
    elif [ -t 0 ]; then
        echo ""
        echo "╔══════════════════════════════════════════════════════════════════════════════╗"
        echo "║  ⚠️  LIVE TRADING — OPERATOR CONFIRMATION REQUIRED                           ║"
        echo "╚══════════════════════════════════════════════════════════════════════════════╝"
        echo ""
        echo "   🔴 REAL MONEY AT RISK. Live orders will be placed on exchanges."
        echo "   Branch: ${BRANCH_VAL:-unknown}  Commit: ${COMMIT_VAL:-unknown}"
        echo ""
        read -p "   Type 'yes' to confirm live trading: " -r
        echo ""
        if [[ ! $REPLY =~ ^[Yy][Ee][Ss]$ ]]; then
            echo "❌ Live trading not confirmed. Exiting."
            echo "   To test safely: export DRY_RUN_MODE=true"
            exit 0
        fi
        echo "✅ Live trading confirmed by operator."
    else
        echo "✅ Live trading approved: LIVE_CAPITAL_VERIFIED=true in non-interactive session."
    fi
fi

# Kraken credentials are REQUIRED (primary broker); Coinbase credentials are OPTIONAL (secondary broker)
if [ -z "${KRAKEN_PLATFORM_API_KEY}" ] || [ -z "${KRAKEN_PLATFORM_API_SECRET}" ]; then
    echo ""
    echo "⚠️  MISSING KRAKEN CREDENTIALS — LIVE MODE REQUIRES API KEY + SECRET"
    echo ""
    echo "Kraken is the primary broker. Coinbase can be connected as a secondary broker."
    echo "Set these environment variables, then re-run:"
    echo "   export KRAKEN_PLATFORM_API_KEY='<your-api-key>'"
    echo "   export KRAKEN_PLATFORM_API_SECRET='<your-api-secret>'"
    echo ""
    echo "Alternatively, place them in .env (now auto-loaded on start)."
    echo ""
    echo "📖 See .env.example for detailed setup instructions"
    echo ""
    exit_config_error
fi

# Enforce live mode explicitly
export PAPER_MODE=false

# Log monitoring guidance — watch for execution errors and trade rejections
echo ""
echo "📋 LOG MONITORING: Logs stream to stdout and nija.log"
echo "   Key patterns to watch:"
echo "      ❌ ORDER REJECTED / EXECUTION ERROR — trade could not be placed"
echo "      ⚠️  API ERROR / RATE LIMITED       — connectivity or throttling issues"
echo "      ⚠️  INSUFFICIENT FUNDS             — balance too low for trade"
echo ""

echo "🔄 Starting live trading bot..."
echo "Working directory: $(pwd)"
echo "Bot file exists: $(test -f ./bot.py && echo 'YES' || echo 'NO')"

# Sleep briefly to ensure all bash output is flushed before Python starts
# This prevents log message interleaving between bash and Python stdout
sleep 0.1

# Startup guard: show first lines of bot.py to detect stale images
if [ -f bot.py ]; then
    echo "--- bot.py (head) ---"
    head -n 10 bot.py || true
    echo "----------------------"

    # Fail-fast: detect stale cached images
    if head -n 1 bot.py | grep -q "NEW BOT.PY IS RUNNING"; then
        echo "❌ Detected stale cached image: RuntimeError banner present in bot.py"
        echo "👉 Delete the Render service and redeploy from the main branch."
        exit 2
    fi
    if head -n 10 bot.py | grep -q "from nija_strategy"; then
        echo "❌ Detected stale cached image: old import 'nija_strategy' in bot.py"
        echo "👉 Delete the Render service and redeploy from the main branch."
        exit 2
    fi
fi

# Start bot.py with full error output (LIVE)
$PY -u bot.py 2>&1
status=$?

# Treat SIGTERM (143) as graceful to avoid restart loops during platform stop/redeploy
if [ "$status" -eq 0 ]; then
    exit 0
fi
if [ "$status" -eq 143 ]; then
    echo "⚠️ Bot received SIGTERM (143). Treating as graceful stop."
    exit 0
fi

echo "❌ Bot crashed! Exit code: $status"
exit 1
