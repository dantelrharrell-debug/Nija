#!/bin/bash
set -e  # Exit on error

echo "=============================="
echo "    STARTING NIJA TRADING BOT"
echo "=============================="

python3 --version

# Test Coinbase module
python3 -c "from coinbase.rest import RESTClient; print('✅ Coinbase REST client available')"

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

# Auto-enable paper mode if credentials are missing
if [ -z "${COINBASE_API_KEY}" ] || [ -z "${COINBASE_API_SECRET}" ]; then
    echo ""
    echo "⚠️  COINBASE CREDENTIALS MISSING — PAPER_MODE ENABLED"
    echo ""
    echo "📋 TO ENABLE LIVE TRADING:"
    echo "   1. Go to Railway dashboard → Nija service → Variables"
    echo "   2. Add these two variables:"
    echo "      - COINBASE_API_KEY = organizations/.../apiKeys/..."
    echo "      - COINBASE_API_SECRET = <your secret string>"
    echo "   3. Remove old variables (COINBASE_PEM_PATH, COINBASE_API_SECRET_PATH)"
    echo "   4. Save and redeploy/restart the service"
    echo ""
    export PAPER_MODE=true
fi

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
        echo "👉 Delete the Railway service and redeploy from the main branch."
        exit 2
    fi
    if head -n 10 bot.py | grep -q "from nija_strategy"; then
        echo "❌ Detected stale cached image: old import 'nija_strategy' in bot.py"
        echo "👉 Delete the Railway service and redeploy from the main branch."
        exit 2
    fi
fi

# Start bot.py with full error output
python3 -u bot.py 2>&1 || {
    echo "❌ Bot crashed! Exit code: $?"
    exit 1
}
