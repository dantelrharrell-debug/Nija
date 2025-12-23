#!/bin/bash
set -e  # Exit on error

echo "=============================="
echo "    STARTING NIJA TRADING BOT"
echo "=============================="

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

$PY --version

# Test Coinbase module
$PY -c "from coinbase.rest import RESTClient; print('✅ Coinbase REST client available')"

BRANCH_VAL=${GIT_BRANCH}
COMMIT_VAL=${GIT_COMMIT}

# Populate branch/commit from git if not provided
if [ -z "$BRANCH_VAL" ] && command -v git >/dev/null 2>&1; then
    BRANCH_VAL=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "unknown")
fi
if [ -z "$COMMIT_VAL" ] && command -v git >/dev/null 2>&1; then
    COMMIT_VAL=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
fi

echo "Branch: ${BRANCH_VAL:-unknown}"
echo "Commit: ${COMMIT_VAL:-unknown}"

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

# Debug: Show credential status
echo ""
echo "🔍 CREDENTIAL STATUS:"
if [ -n "${COINBASE_API_KEY}" ]; then
    echo "   ✅ COINBASE_API_KEY is set (${#COINBASE_API_KEY} chars)"
else
    echo "   ❌ COINBASE_API_KEY is missing or empty"
fi
if [ -n "${COINBASE_API_SECRET}" ]; then
    echo "   ✅ COINBASE_API_SECRET is set (${#COINBASE_API_SECRET} chars)"
else
    echo "   ❌ COINBASE_API_SECRET is missing or empty"
fi
echo ""
echo "🔧 Trading Guards:"
echo "   MIN_CASH_TO_BUY=${MIN_CASH_TO_BUY:-5.0}"
echo "   MINIMUM_TRADING_BALANCE=${MINIMUM_TRADING_BALANCE:-25.0}"
echo ""

# Require credentials for LIVE mode; do NOT fall back to PAPER_MODE
if [ -z "${COINBASE_API_KEY}" ] || [ -z "${COINBASE_API_SECRET}" ]; then
    echo ""
    echo "⚠️  MISSING COINBASE CREDENTIALS — LIVE MODE REQUIRES API KEY + SECRET"
    echo ""
    echo "Set these environment variables, then re-run:"
    echo "   export COINBASE_API_KEY='organizations/...'"
    echo "   export COINBASE_API_SECRET='-----BEGIN PRIVATE KEY-----\n...'"
    echo ""
    echo "Alternatively, place them in .env (now auto-loaded on start)."
    echo ""
    exit 1
fi

# Enforce live mode explicitly
export PAPER_MODE=false

echo "🔄 Starting live trading bot..."
echo "Working directory: $(pwd)"
echo "Bot file exists: $(test -f ./bot.py && echo 'YES' || echo 'NO')"

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
