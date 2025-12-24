#!/bin/bash
# EMERGENCY ACTION GUIDE - 2025-12-24
# Use this to take immediate action on your bleeding account

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${RED}================================================${NC}"
echo -e "${RED}🚨 NIJA BOT - EMERGENCY CONTROL CENTER${NC}"
echo -e "${RED}================================================${NC}"
echo ""

echo -e "${BLUE}1️⃣  EMERGENCY STOP - Sell-Only Mode${NC}"
echo "   Creates TRADING_EMERGENCY_STOP.conf"
echo "   Bot will manage existing positions but NOT open new ones"
echo "   Usage: bash emergency_actions.sh stop"
echo ""

echo -e "${BLUE}2️⃣  FORCE EXIT ALL - Close Everything${NC}"
echo "   Creates FORCE_EXIT_ALL.conf"
echo "   ⚠️  CLOSES ALL POSITIONS AT MARKET PRICE IMMEDIATELY"
echo "   Usage: bash emergency_actions.sh exit"
echo ""

echo -e "${BLUE}3️⃣  RESUME NORMAL - Re-enable Trading${NC}"
echo "   Removes emergency lock files"
echo "   Bot will resume opening new positions when balance > \$25"
echo "   Usage: bash emergency_actions.sh resume"
echo ""

echo -e "${YELLOW}📊 CURRENT STATUS:${NC}"
echo "   • Trading Loop: 2.5 minutes (was 15 seconds)"
echo "   • Buying Guard: Disabled if balance < \$25"
echo "   • Cooldown: 60 minutes after selling a position"
echo "   • Status: EMERGENCY FIX ACTIVE"
echo ""

# Handle command line arguments
if [ "$1" = "stop" ]; then
    echo -e "${RED}Creating TRADING_EMERGENCY_STOP.conf...${NC}"
    touch TRADING_EMERGENCY_STOP.conf
    echo -e "${GREEN}✅ Emergency stop activated${NC}"
    echo "   Bot is now in SELL-ONLY mode"
    echo "   Existing positions will be managed, no new buys"
    
elif [ "$1" = "exit" ]; then
    echo -e "${RED}Creating FORCE_EXIT_ALL.conf...${NC}"
    read -p "⚠️  This will close ALL positions. Are you sure? (yes/no): " confirm
    if [ "$confirm" = "yes" ]; then
        touch FORCE_EXIT_ALL.conf
        echo -e "${GREEN}✅ Force exit requested${NC}"
        echo "   All positions will close on next trading cycle"
        echo "   Check logs for execution details"
    else
        echo "   Cancelled"
    fi
    
elif [ "$1" = "resume" ]; then
    echo -e "${GREEN}Removing emergency lock files...${NC}"
    rm -f TRADING_EMERGENCY_STOP.conf FORCE_EXIT_ALL.conf
    echo -e "${GREEN}✅ Trading resumed to normal${NC}"
    echo "   Bot will open new positions when balance > \$25"
    
elif [ "$1" = "check" ]; then
    echo -e "${YELLOW}Current emergency status:${NC}"
    if [ -f "TRADING_EMERGENCY_STOP.conf" ]; then
        echo -e "${RED}   • EMERGENCY STOP active (sell-only mode)${NC}"
    else
        echo -e "${GREEN}   • Emergency stop NOT active${NC}"
    fi
    
    if [ -f "FORCE_EXIT_ALL.conf" ]; then
        echo -e "${RED}   • FORCE EXIT pending (will close all positions)${NC}"
    else
        echo -e "${GREEN}   • Force exit NOT pending${NC}"
    fi
    
else
    echo -e "${YELLOW}Usage:${NC}"
    echo "  bash emergency_actions.sh stop      # Sell-only mode"
    echo "  bash emergency_actions.sh exit      # Force close all positions"
    echo "  bash emergency_actions.sh resume    # Resume normal trading"
    echo "  bash emergency_actions.sh check     # Check current status"
fi

echo ""
echo -e "${BLUE}❓ Need help?${NC}"
echo "   Read: EMERGENCY_BLEEDING_FIX_DEPLOYED.md"
echo "   Logs: nija.log"
