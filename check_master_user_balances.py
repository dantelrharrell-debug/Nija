#!/usr/bin/env python3
"""
Check Master and User Account Balances on Kraken

This script:
1. Connects to Kraken for both master and user accounts
2. Displays balances for each account
3. Shows trading status for each account
"""

import os
import sys
import logging

# Setup path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

# Try to load dotenv if available
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(message)s'
)
logger = logging.getLogger(__name__)

from multi_account_broker_manager import multi_account_broker_manager, BrokerType


def check_master_user_balances():
    """Check and display balances for master and user accounts."""
    
    logger.info("")
    logger.info("=" * 70)
    logger.info("NIJA MASTER & USER ACCOUNT BALANCE CHECK")
    logger.info("=" * 70)
    logger.info("")
    
    # Add master Kraken broker
    logger.info("🔍 Connecting to MASTER Kraken account...")
    master_kraken = multi_account_broker_manager.add_master_broker(BrokerType.KRAKEN)
    
    # Add master Coinbase broker (if configured)
    logger.info("")
    logger.info("🔍 Connecting to MASTER Coinbase account...")
    master_coinbase = multi_account_broker_manager.add_master_broker(BrokerType.COINBASE)
    
    # Add user Kraken broker (Daivon Frazier)
    logger.info("")
    logger.info("🔍 Connecting to USER Kraken account (daivon_frazier)...")
    user_kraken = multi_account_broker_manager.add_user_broker('daivon_frazier', BrokerType.KRAKEN)
    
    # Display status report
    logger.info("")
    logger.info(multi_account_broker_manager.get_status_report())
    
    # Get detailed balances
    balances = multi_account_broker_manager.get_all_balances()
    
    # Summary
    logger.info("")
    logger.info("=" * 70)
    logger.info("SUMMARY")
    logger.info("=" * 70)
    
    # Master total
    master_total = sum(balances['master'].values())
    logger.info(f"\n🔷 MASTER TOTAL: ${master_total:,.2f}")
    for broker, balance in balances['master'].items():
        logger.info(f"   {broker.upper()}: ${balance:,.2f}")
    
    # User totals
    logger.info(f"\n🔷 USER TOTALS:")
    for user_id, user_balances in balances['users'].items():
        user_total = sum(user_balances.values())
        logger.info(f"\n   {user_id}: ${user_total:,.2f}")
        for broker, balance in user_balances.items():
            logger.info(f"      {broker.upper()}: ${balance:,.2f}")
    
    logger.info("")
    logger.info("=" * 70)
    logger.info("")
    
    # Check if both master and user are trading on Kraken
    logger.info("=" * 70)
    logger.info("TRADING STATUS")
    logger.info("=" * 70)
    logger.info("")
    
    if master_kraken and master_kraken.connected:
        logger.info("✅ MASTER is trading on Kraken")
    else:
        logger.info("❌ MASTER is NOT trading on Kraken (not configured or connection failed)")
    
    if user_kraken and user_kraken.connected:
        logger.info("✅ USER (daivon_frazier) is trading on Kraken")
    else:
        logger.info("❌ USER (daivon_frazier) is NOT trading on Kraken (not configured or connection failed)")
    
    logger.info("")
    logger.info("=" * 70)
    logger.info("")
    
    # Instructions if master Kraken not configured
    if not master_kraken or not master_kraken.connected:
        logger.info("")
        logger.info("⚠️  MASTER KRAKEN NOT CONFIGURED")
        logger.info("")
        logger.info("To enable master Kraken trading:")
        logger.info("1. Get Kraken API credentials for master account")
        logger.info("2. Add to .env file:")
        logger.info("   KRAKEN_MASTER_API_KEY=your_master_api_key")
        logger.info("   KRAKEN_MASTER_API_SECRET=your_master_api_secret")
        logger.info("3. Restart the bot")
        logger.info("")


if __name__ == "__main__":
    try:
        check_master_user_balances()
    except Exception as e:
        logger.error(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
