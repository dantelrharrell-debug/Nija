#!/usr/bin/env python3
"""
Test script to verify enhanced warning messages for missing Master accounts.
This simulates the warning output when users are connected but Master account is not.
"""

import logging
import sys

# Setup logging to match the bot's format
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

logger = logging.getLogger('nija.multi_account')

def simulate_warnings_for_missing_master():
    """Simulate the enhanced warning output"""
    
    # Simulate that KRAKEN has users but no master
    users_without_master = ["KRAKEN"]
    
    logger.info("=" * 70)
    logger.info("📊 ACCOUNT HIERARCHY REPORT")
    logger.info("=" * 70)
    logger.info("🎯 MASTER accounts are PRIMARY - User accounts are SECONDARY")
    logger.info("=" * 70)
    
    # Show Master broker status
    logger.info("🔷 MASTER ACCOUNTS (Primary Trading Accounts):")
    logger.info("   • COINBASE: ✅ CONNECTED")
    logger.info("   • KRAKEN: ❌ NOT CONNECTED")
    
    logger.info("")
    logger.info("👤 USER ACCOUNTS (Secondary Trading Accounts):")
    logger.info(f"   ✅ 2 user(s) connected across 1 brokerage(s)")
    logger.info(f"   • KRAKEN: 2 user(s)")
    
    # Log warnings for problematic setups
    logger.info("")
    logger.info("⚠️  ACCOUNT PRIORITY WARNINGS:")
    
    if users_without_master:
        logger.warning(f"   ⚠️  User accounts trading WITHOUT Master account on: {', '.join(users_without_master)}")
        logger.warning(f"   🔧 RECOMMENDATION: Configure Master credentials for {', '.join(users_without_master)}")
        logger.warning(f"      Master should always be PRIMARY, users should be SECONDARY")
        logger.warning("")
        logger.warning("   📋 HOW TO FIX:")
        for broker in users_without_master:
            logger.warning(f"")
            logger.warning(f"   For {broker} Master account:")
            logger.warning(f"   1. Get API credentials from the {broker} website")
            if broker == "KRAKEN":
                logger.warning(f"      URL: https://www.kraken.com/u/security/api")
                logger.warning(f"   2. Set these environment variables:")
                logger.warning(f"      KRAKEN_MASTER_API_KEY=<your-api-key>")
                logger.warning(f"      KRAKEN_MASTER_API_SECRET=<your-api-secret>")
            elif broker == "ALPACA":
                logger.warning(f"      URL: https://alpaca.markets/")
                logger.warning(f"   2. Set these environment variables:")
                logger.warning(f"      ALPACA_API_KEY=<your-api-key>")
                logger.warning(f"      ALPACA_API_SECRET=<your-api-secret>")
                logger.warning(f"      ALPACA_PAPER=true  # Use false for live trading")
            elif broker == "COINBASE":
                logger.warning(f"      URL: https://portal.cdp.coinbase.com/")
                logger.warning(f"   2. Set these environment variables:")
                logger.warning(f"      COINBASE_API_KEY=<your-api-key>")
                logger.warning(f"      COINBASE_API_SECRET=<your-api-secret>")
            else:
                logger.warning(f"   2. Set {broker}_MASTER_API_KEY and {broker}_MASTER_API_SECRET")
            logger.warning(f"   3. Restart the bot")
        logger.warning("")
        logger.warning("   💡 TIP: Once Master accounts are connected, the warning will disappear")
        logger.warning("=" * 70)
    else:
        logger.info("   ✅ All user accounts have corresponding Master accounts (correct hierarchy)")
    
    logger.info("=" * 70)

if __name__ == "__main__":
    print("\n" + "="*80)
    print("SIMULATING ENHANCED WARNING OUTPUT")
    print("="*80)
    print("\nScenario: KRAKEN users are connected, but KRAKEN Master is NOT connected\n")
    
    simulate_warnings_for_missing_master()
    
    print("\n" + "="*80)
    print("TEST COMPLETE")
    print("="*80)
