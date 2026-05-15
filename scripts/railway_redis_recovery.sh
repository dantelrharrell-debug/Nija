#!/bin/bash
# 🚨 NIJA Redis Lock - RAILWAY RECOVERY SCRIPT
# Run this script to complete one of the recovery options
# Usage: bash scripts/railway_redis_recovery.sh

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${CYAN}"
echo "╔════════════════════════════════════════════════════════════╗"
echo "║     NIJA REDIS LOCK RECOVERY - RAILWAY SETUP HELPER       ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo -e "${NC}"

echo -e "\n${BLUE}This script will help you fix the Redis lock issue.${NC}"
echo "Choose one option based on your diagnosis:"
echo ""
echo -e "${YELLOW}1${NC}) Restart Redis service (most common fix)"
echo -e "${YELLOW}2${NC}) Enable TCP Proxy for Redis"
echo -e "${YELLOW}3${NC}) Update NIJA_REDIS_URL environment variable"
echo -e "${YELLOW}4${NC}) Fail over to alternate Redis endpoint"
echo -e "${YELLOW}5${NC}) Show diagnostic info"
echo ""

read -p "Enter choice (1-5): " choice

case $choice in
  1)
    echo -e "\n${BLUE}════════════════════════════════════════════════════════════${NC}"
    echo -e "${BLUE}STEP 1: Restart Redis Service${NC}"
    echo -e "${BLUE}════════════════════════════════════════════════════════════${NC}\n"
    
    echo -e "${GREEN}✅ Instructions:${NC}"
    echo "   1. Open Railway dashboard: https://railway.app"
    echo "   2. Select your project"
    echo "   3. Click on the 'Redis' service"
    echo "   4. Click the 'Restart' button (top right)"
    echo "   5. Wait 30-60 seconds for it to come back online"
    echo "   6. Status should change from 🔴 Red to 🟢 Green"
    echo "   7. Then restart the 'NIJA' service"
    echo ""
    echo -e "${YELLOW}Why this works:${NC}"
    echo "   - Redis may have crashed or hit memory limits"
    echo "   - Restart forces it to reconnect and clear stale state"
    echo ""
    ;;
    
  2)
    echo -e "\n${BLUE}════════════════════════════════════════════════════════════${NC}"
    echo -e "${BLUE}STEP 2: Enable TCP Proxy for Redis${NC}"
    echo -e "${BLUE}════════════════════════════════════════════════════════════${NC}\n"
    
    echo -e "${GREEN}✅ Instructions:${NC}"
    echo "   1. Open Railway dashboard: https://railway.app"
    echo "   2. Select your project"
    echo "   3. Click on the 'Redis' service"
    echo "   4. Go to the 'Networking' tab"
    echo "   5. Look for 'Public Networking' or 'TCP Proxy'"
    echo "   6. If it says 'Disabled', click to enable it"
    echo "   7. Wait for it to activate (shows 🟢 Green)"
    echo "   8. Copy both the Domain and Port shown"
    echo ""
    echo -e "${YELLOW}Note:${NC}"
    echo "   If 'Networking' tab doesn't exist, your Railway plan"
    echo "   may not support custom networking. Try the emergency bypass instead."
    echo ""
    ;;
    
  3)
    echo -e "\n${BLUE}════════════════════════════════════════════════════════════${NC}"
    echo -e "${BLUE}STEP 3: Update NIJA_REDIS_URL${NC}"
    echo -e "${BLUE}════════════════════════════════════════════════════════════${NC}\n"
    
    echo -e "${GREEN}✅ Instructions:${NC}"
    echo ""
    echo "   A. GET INFO FROM REDIS SERVICE:"
    echo "      1. Go to Redis service → Variables"
    echo "      2. Find REDIS_PASSWORD and copy it"
    echo "      3. Go to Redis service → Networking"
    echo "      4. Copy the Domain (e.g., maglev.proxy.rlwy.net)"
    echo "      5. Copy the Port (e.g., 31245)"
    echo ""
    echo "   B. UPDATE NIJA ENVIRONMENT:"
    echo "      1. Go to NIJA service → Variables"
    echo "      2. Create or update NIJA_REDIS_URL:"
    echo ""
    echo -e "      ${CYAN}NIJA_REDIS_URL=rediss://default:YOUR_PASSWORD@YOUR_HOST:YOUR_PORT/0${NC}"
    echo ""
    echo "      Example:"
    echo -e "      ${CYAN}NIJA_REDIS_URL=rediss://default:2eF9xK_3mL#pQ@maglev.proxy.rlwy.net:31245/0${NC}"
    echo ""
    echo "      Replace:"
    echo "      - YOUR_PASSWORD: value from REDIS_PASSWORD"
    echo "      - YOUR_HOST: domain from Networking tab"
    echo "      - YOUR_PORT: port from Networking tab"
    echo ""
    echo "   3. Save and restart NIJA service"
    echo ""
    echo -e "${YELLOW}Important:${NC}"
    echo "   • Use rediss:// (with 'ss'), NOT redis://"
    echo "   • Include the RedisPassword in the URL"
    echo "   • Port should NOT be 6379 for TCP proxy"
    echo ""
    ;;
    
  4)
    echo -e "\n${BLUE}════════════════════════════════════════════════════════════${NC}"
    echo -e "${BLUE}STEP 4: Fail Over to Alternate Redis Endpoint${NC}"
    echo -e "${BLUE}════════════════════════════════════════════════════════════${NC}\n"
    
    echo -e "${YELLOW}Use this when the current proxy endpoint is down or unstable.${NC}"
    echo ""
    echo -e "${GREEN}✅ Instructions:${NC}"
    echo "   1. In Railway, open Redis service → Connect / Variables"
    echo "   2. Collect at least two candidate endpoints:"
    echo "      • Internal/private host (preferred when NIJA runs inside Railway)"
    echo "      • Public proxy host (fallback)"
    echo "   3. In NIJA service → Variables, set the primary endpoint:"
    echo ""
    echo -e "      ${CYAN}NIJA_REDIS_URL=redis://default:YOUR_PASSWORD@YOUR_INTERNAL_HOST:6379/0${NC}"
    echo ""
    echo "      If using a public Railway proxy endpoint, use TLS:"
    echo -e "      ${CYAN}NIJA_REDIS_URL=rediss://default:YOUR_PASSWORD@YOUR_PROXY_HOST:YOUR_PROXY_PORT/0${NC}"
    echo ""
    echo "   4. Add alternate URL variables for runtime fallback candidates:"
    echo -e "      ${CYAN}REDIS_PRIVATE_URL=redis://default:YOUR_PASSWORD@YOUR_INTERNAL_HOST:6379/0${NC}"
    echo -e "      ${CYAN}REDIS_PUBLIC_URL=rediss://default:YOUR_PASSWORD@YOUR_PROXY_HOST:YOUR_PROXY_PORT/0${NC}"
    echo ""
    echo "   5. Restart NIJA service"
    echo "   6. Verify with preflight:"
    echo -e "      ${CYAN}python -m bot.production_preflight${NC}"
    echo ""
    echo -e "${YELLOW}Important:${NC}"
    echo "   • Do NOT bypass distributed lock enforcement in live mode."
    echo "   • If all endpoints fail, treat as Redis provider outage and rotate endpoint/service."
    echo ""
    ;;
    
  5)
    echo -e "\n${BLUE}════════════════════════════════════════════════════════════${NC}"
    echo -e "${BLUE}DIAGNOSTIC INFORMATION${NC}"
    echo -e "${BLUE}════════════════════════════════════════════════════════════${NC}\n"
    
    echo -e "${GREEN}Current Environment:${NC}"
    if command -v python3 &> /dev/null; then
      python3 -c "
import os
from urllib.parse import urlparse

print('NIJA_REDIS_URL:', 'SET' if os.environ.get('NIJA_REDIS_URL') else 'NOT SET')
print('REDIS_URL:', 'SET' if os.environ.get('REDIS_URL') else 'NOT SET')
print('REDIS_PASSWORD:', 'SET' if os.environ.get('REDIS_PASSWORD') else 'NOT SET')
print('LIVE_CAPITAL_VERIFIED:', os.environ.get('LIVE_CAPITAL_VERIFIED', 'NOT SET'))

url = os.environ.get('NIJA_REDIS_URL') or os.environ.get('REDIS_URL')
if url:
  try:
    parsed = urlparse(url)
    print(f'Redis Host: {parsed.hostname}')
    print(f'Redis Port: {parsed.port}')
    print(f'TLS Enabled: {parsed.scheme in (\"rediss\", \"redis+ssl\")}')
  except:
    pass
" 2>/dev/null || echo "(unable to parse - run diagnostic script)"
    else
      echo "python3 not found - cannot show diagnostics"
    fi
    echo ""
    echo -e "${GREEN}Full diagnosis (detailed):${NC}"
    echo "   bash scripts/redis_connectivity_check.sh"
    echo ""
    ;;
    
  *)
    echo -e "${RED}❌ Invalid choice${NC}"
    exit 1
    ;;
esac

echo -e "\n${CYAN}═══════════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}✅ Follow the steps above in Railway dashboard${NC}"
echo -e "${GREEN}✅ After making changes, restart the NIJA service${NC}"
echo -e "${GREEN}✅ Check logs for: 'Distributed writer lock acquired'${NC}"
echo -e "${CYAN}═══════════════════════════════════════════════════════════${NC}\n"
