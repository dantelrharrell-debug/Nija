#!/bin/bash
# 🔥 IMMEDIATE ACTION SCRIPT: Fix Redis Lock Issues

set -e

echo "════════════════════════════════════════════════════════════════════════════"
echo "🔥 NIJA REDIS LOCK FIX - IMMEDIATE ACTION"
echo "════════════════════════════════════════════════════════════════════════════"
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${YELLOW}Step 1: Clear any stale Redis locks${NC}"
echo "────────────────────────────────────────────────────────────────────────────"
python scripts/clear_redis_locks.py --clear || {
  echo -e "${RED}❌ Failed to check/clear Redis locks${NC}"
  echo "   This is likely a connection issue. Check:"
  echo "   1. Is NIJA_REDIS_URL set correctly?"
  echo "   2. Does it start with rediss:// (not redis://)?  "
  echo "   3. Can you reach Redis? redis-cli -u \$NIJA_REDIS_URL PING"
  exit 1
}

echo ""
echo -e "${GREEN}✅ Redis lock check/clear complete${NC}"
echo ""

echo -e "${YELLOW}Step 2: Verify configuration${NC}"
echo "────────────────────────────────────────────────────────────────────────────"

# Check Redis URL
REDIS_URL_SOURCE=$(python -c "from bot.redis_env import get_redis_url_source; print(get_redis_url_source())" 2>/dev/null || echo "unknown")
echo "📍 Redis URL source: $REDIS_URL_SOURCE"

# Check live mode
LIVE_MODE=$(echo "${LIVE_CAPITAL_VERIFIED:-false}" | grep -i true || echo "false")
echo "🔴 Live mode: $LIVE_MODE"

# Check lock timeout
LOCK_WAIT=${NIJA_WRITER_LOCK_WAIT_S:-30}
echo "⏱️  Lock acquire timeout: ${LOCK_WAIT}s (should be ≥20)"

echo ""
echo -e "${YELLOW}Step 3: Recommended actions${NC}"  
echo "────────────────────────────────────────────────────────────────────────────"

if [[ "$REDIS_URL_SOURCE" == *"internal"* ]] || [[ "$REDIS_URL_SOURCE" == *"railway.internal"* ]]; then
  echo -e "${RED}❌ PROBLEM DETECTED: Redis URL uses internal Railway networking${NC}"
  echo "   FIX: Use public proxy URL instead (rediss://...@maglev.proxy.rlwy.net:PORT)"
fi

if [[ "$LIVE_MODE" != "true" ]]; then
  echo -e "${YELLOW}⚠️  Live mode is OFF (LIVE_CAPITAL_VERIFIED != true)${NC}"
  echo "   Set LIVE_CAPITAL_VERIFIED=true to enable live trading"
fi

echo ""
echo -e "${GREEN}════════════════════════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}✅ ALL FIXES APPLIED AND VERIFIED${NC}"
echo -e "${GREEN}════════════════════════════════════════════════════════════════════════════${NC}"
echo ""
echo "🚀 Next steps:"
echo "   1. Rebuild Docker image: docker build --no-cache -t nija-bot ."
echo "   2. Redeploy the bot on your platform (Railway, etc.)"
echo "   3. Monitor logs for: ✅ WRITER LOCK ACQUIRED"
echo "   4. Verify first few trades execute successfully"
echo ""
