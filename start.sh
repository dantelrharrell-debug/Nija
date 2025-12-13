#!/bin/bash
set -e  # Exit on error

echo "=============================="
echo "    STARTING NIJA TRADING BOT"
echo "=============================="

python3 --version

# Test Coinbase module
python3 -c "from coinbase.rest import RESTClient; print('✅ Coinbase REST client available')"

echo "Branch: ${GIT_BRANCH:-unknown}"
echo "Commit: ${GIT_COMMIT:-unknown}"

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
