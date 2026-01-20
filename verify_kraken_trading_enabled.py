#!/usr/bin/env python3
"""
Kraken Trading Verification Script
===================================

This script verifies that Kraken is properly configured and ready to trade
for both master and user accounts.

Run this script to check:
1. Kraken API credentials are set
2. Kraken master broker can connect
3. Kraken users can connect
4. Copy trading engine is configured correctly
5. Minimum balance requirements are met

Usage:
    python3 verify_kraken_trading_enabled.py
"""

import os
import sys
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s'
)
logger = logging.getLogger(__name__)

def verify_environment_variables():
    """Check if Kraken environment variables are set."""
    logger.info("=" * 70)
    logger.info("🔍 STEP 1: Verifying Environment Variables")
    logger.info("=" * 70)
    
    master_key = os.getenv("KRAKEN_MASTER_API_KEY", "")
    master_secret = os.getenv("KRAKEN_MASTER_API_SECRET", "")
    
    daivon_key = os.getenv("KRAKEN_USER_DAIVON_API_KEY", "")
    daivon_secret = os.getenv("KRAKEN_USER_DAIVON_API_SECRET", "")
    
    tania_key = os.getenv("KRAKEN_USER_TANIA_API_KEY", "")
    tania_secret = os.getenv("KRAKEN_USER_TANIA_API_SECRET", "")
    
    # Master account
    if master_key and master_secret:
        logger.info("✅ KRAKEN_MASTER credentials: SET")
        logger.info(f"   Key length: {len(master_key)} chars")
        logger.info(f"   Secret length: {len(master_secret)} chars")
        master_ok = True
    else:
        logger.warning("❌ KRAKEN_MASTER credentials: NOT SET")
        logger.warning("   Required: KRAKEN_MASTER_API_KEY and KRAKEN_MASTER_API_SECRET")
        master_ok = False
    
    logger.info("")
    
    # User #1: Daivon
    if daivon_key and daivon_secret:
        logger.info("✅ KRAKEN_USER_DAIVON credentials: SET")
        logger.info(f"   Key length: {len(daivon_key)} chars")
        logger.info(f"   Secret length: {len(daivon_secret)} chars")
        daivon_ok = True
    else:
        logger.warning("⚠️  KRAKEN_USER_DAIVON credentials: NOT SET")
        logger.warning("   Optional: KRAKEN_USER_DAIVON_API_KEY and KRAKEN_USER_DAIVON_API_SECRET")
        daivon_ok = False
    
    logger.info("")
    
    # User #2: Tania
    if tania_key and tania_secret:
        logger.info("✅ KRAKEN_USER_TANIA credentials: SET")
        logger.info(f"   Key length: {len(tania_key)} chars")
        logger.info(f"   Secret length: {len(tania_secret)} chars")
        tania_ok = True
    else:
        logger.warning("⚠️  KRAKEN_USER_TANIA credentials: NOT SET")
        logger.warning("   Optional: KRAKEN_USER_TANIA_API_KEY and KRAKEN_USER_TANIA_API_SECRET")
        tania_ok = False
    
    logger.info("=" * 70)
    logger.info("")
    
    return {
        'master': master_ok,
        'daivon': daivon_ok,
        'tania': tania_ok
    }

def verify_kraken_sdk():
    """Check if Kraken SDK is installed."""
    logger.info("=" * 70)
    logger.info("🔍 STEP 2: Verifying Kraken SDK Installation")
    logger.info("=" * 70)
    
    try:
        import krakenex
        logger.info("✅ krakenex: INSTALLED")
        logger.info(f"   Version: {krakenex.__version__ if hasattr(krakenex, '__version__') else 'unknown'}")
    except ImportError as e:
        logger.error("❌ krakenex: NOT INSTALLED")
        logger.error(f"   Error: {e}")
        logger.error("")
        logger.error("   Fix: pip install krakenex")
        return False
    
    try:
        import pykrakenapi
        logger.info("✅ pykrakenapi: INSTALLED")
        logger.info(f"   Version: {pykrakenapi.__version__ if hasattr(pykrakenapi, '__version__') else 'unknown'}")
    except ImportError as e:
        logger.error("❌ pykrakenapi: NOT INSTALLED")
        logger.error(f"   Error: {e}")
        logger.error("")
        logger.error("   Fix: pip install pykrakenapi")
        return False
    
    logger.info("=" * 70)
    logger.info("")
    return True

def verify_broker_connection(credentials):
    """Test Kraken broker connection."""
    logger.info("=" * 70)
    logger.info("🔍 STEP 3: Testing Kraken Broker Connections")
    logger.info("=" * 70)
    
    # Add bot directory to path
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))
    
    try:
        from broker_manager import KrakenBroker, AccountType
    except ImportError as e:
        logger.error(f"❌ Failed to import KrakenBroker: {e}")
        return False
    
    connections = {}
    
    # Test master connection
    if credentials['master']:
        logger.info("Testing KRAKEN MASTER connection...")
        try:
            master = KrakenBroker(account_type=AccountType.MASTER)
            if master.connect():
                balance = master.get_account_balance()
                logger.info(f"✅ KRAKEN MASTER: CONNECTED")
                logger.info(f"   Balance: ${balance:,.2f}")
                if balance >= 0.50:
                    logger.info(f"   Status: FUNDED (minimum $0.50 met)")
                    connections['master'] = True
                else:
                    logger.warning(f"   Status: UNDERFUNDED (need $0.50+, have ${balance:.2f})")
                    connections['master'] = False
            else:
                logger.error("❌ KRAKEN MASTER: CONNECTION FAILED")
                logger.error(f"   Error: {master.last_connection_error if hasattr(master, 'last_connection_error') else 'Unknown'}")
                connections['master'] = False
        except Exception as e:
            logger.error(f"❌ KRAKEN MASTER: ERROR - {e}")
            import traceback
            logger.error(traceback.format_exc())
            connections['master'] = False
        logger.info("")
    else:
        logger.warning("⏭️  Skipping KRAKEN MASTER (credentials not set)")
        connections['master'] = False
        logger.info("")
    
    # Test user connections
    # Map user names to their full user IDs
    user_id_map = {
        'daivon': 'daivon_frazier',
        'tania': 'tania_gilbert'
    }
    
    for user_name in ['daivon', 'tania']:
        if credentials[user_name]:
            logger.info(f"Testing KRAKEN USER ({user_name.upper()}) connection...")
            try:
                user_id = user_id_map[user_name]
                user_broker = KrakenBroker(account_type=AccountType.USER, user_id=user_id)
                if user_broker.connect():
                    balance = user_broker.get_account_balance()
                    logger.info(f"✅ KRAKEN USER ({user_name.upper()}): CONNECTED")
                    logger.info(f"   Balance: ${balance:,.2f}")
                    if balance >= 0.50:
                        logger.info(f"   Status: FUNDED (minimum $0.50 met)")
                        connections[user_name] = True
                    else:
                        logger.warning(f"   Status: UNDERFUNDED (need $0.50+, have ${balance:.2f})")
                        connections[user_name] = False
                else:
                    logger.error(f"❌ KRAKEN USER ({user_name.upper()}): CONNECTION FAILED")
                    logger.error(f"   Error: {user_broker.last_connection_error if hasattr(user_broker, 'last_connection_error') else 'Unknown'}")
                    connections[user_name] = False
            except Exception as e:
                logger.error(f"❌ KRAKEN USER ({user_name.upper()}): ERROR - {e}")
                import traceback
                logger.error(traceback.format_exc())
                connections[user_name] = False
            logger.info("")
        else:
            logger.warning(f"⏭️  Skipping KRAKEN USER ({user_name.upper()}) (credentials not set)")
            connections[user_name] = False
            logger.info("")
    
    logger.info("=" * 70)
    logger.info("")
    return connections

def verify_copy_trading_config():
    """Check copy trading engine configuration."""
    logger.info("=" * 70)
    logger.info("🔍 STEP 4: Verifying Copy Trading Configuration")
    logger.info("=" * 70)
    
    try:
        # Check if bot.py has copy trading enabled
        bot_file = os.path.join(os.path.dirname(__file__), 'bot.py')
        if os.path.exists(bot_file):
            with open(bot_file, 'r') as f:
                content = f.read()
                
                # Check for observe_only=False (active mode)
                if 'start_copy_engine(observe_only=False)' in content:
                    logger.info("✅ Copy trading engine: ACTIVE MODE")
                    logger.info("   observe_only=False (trades will be executed)")
                    copy_active = True
                elif 'start_copy_engine(observe_only=True)' in content:
                    logger.warning("⚠️  Copy trading engine: OBSERVE MODE")
                    logger.warning("   observe_only=True (trades will NOT be executed)")
                    logger.warning("   User accounts will see signals but won't trade")
                    copy_active = False
                else:
                    logger.warning("⚠️  Copy trading engine configuration unclear")
                    copy_active = None
        else:
            logger.error("❌ bot.py not found")
            copy_active = None
    except Exception as e:
        logger.error(f"❌ Error checking copy trading config: {e}")
        copy_active = None
    
    logger.info("=" * 70)
    logger.info("")
    return copy_active

def main():
    """Run all verification checks."""
    logger.info("")
    logger.info("=" * 70)
    logger.info("🚀 KRAKEN TRADING VERIFICATION")
    logger.info("=" * 70)
    logger.info("")
    
    # Step 1: Environment variables
    credentials = verify_environment_variables()
    
    # Step 2: SDK installation
    sdk_ok = verify_kraken_sdk()
    if not sdk_ok:
        logger.error("")
        logger.error("=" * 70)
        logger.error("❌ VERIFICATION FAILED: Kraken SDK not installed")
        logger.error("=" * 70)
        logger.error("Install with: pip install krakenex pykrakenapi")
        logger.error("=" * 70)
        return 1
    
    # Step 3: Broker connections
    connections = verify_broker_connection(credentials)
    
    # Step 4: Copy trading configuration
    copy_active = verify_copy_trading_config()
    
    # Summary
    logger.info("=" * 70)
    logger.info("📊 VERIFICATION SUMMARY")
    logger.info("=" * 70)
    logger.info("")
    
    logger.info("Credentials Configuration:")
    logger.info(f"   MASTER: {'✅ SET' if credentials['master'] else '❌ NOT SET'}")
    logger.info(f"   USER (Daivon): {'✅ SET' if credentials['daivon'] else '⚠️  NOT SET'}")
    logger.info(f"   USER (Tania): {'✅ SET' if credentials['tania'] else '⚠️  NOT SET'}")
    logger.info("")
    
    logger.info("Broker Connections:")
    logger.info(f"   MASTER: {'✅ CONNECTED & FUNDED' if connections.get('master') else '❌ NOT READY'}")
    logger.info(f"   USER (Daivon): {'✅ CONNECTED & FUNDED' if connections.get('daivon') else '❌ NOT READY'}")
    logger.info(f"   USER (Tania): {'✅ CONNECTED & FUNDED' if connections.get('tania') else '❌ NOT READY'}")
    logger.info("")
    
    logger.info("Copy Trading:")
    if copy_active is True:
        logger.info("   ✅ ACTIVE MODE (trades will execute)")
    elif copy_active is False:
        logger.info("   ⚠️  OBSERVE MODE (trades will NOT execute)")
    else:
        logger.info("   ❌ Configuration unclear")
    logger.info("")
    
    # Overall status
    master_ready = connections.get('master', False)
    users_ready = connections.get('daivon', False) or connections.get('tania', False)
    copy_enabled = copy_active is True
    
    if master_ready and copy_enabled:
        logger.info("=" * 70)
        logger.info("✅ KRAKEN IS READY TO TRADE!")
        logger.info("=" * 70)
        logger.info("")
        logger.info("What happens now:")
        logger.info("   1. Kraken MASTER broker will execute trades based on strategy signals")
        logger.info("   2. When MASTER places a trade, it emits a signal")
        logger.info("   3. Copy trading engine receives the signal")
        if users_ready:
            logger.info("   4. Copy trading engine replicates trade to funded user accounts")
            logger.info("   5. User position sizes are scaled based on balance ratios")
        else:
            logger.info("   4. No funded user accounts - only MASTER will trade")
        logger.info("")
        logger.info("To start trading:")
        logger.info("   python3 bot.py")
        logger.info("=" * 70)
        return 0
    else:
        logger.error("=" * 70)
        logger.error("❌ KRAKEN IS NOT READY TO TRADE")
        logger.error("=" * 70)
        logger.error("")
        if not master_ready:
            logger.error("Issues to fix:")
            logger.error("   ❌ Kraken MASTER is not connected or not funded")
            logger.error("      - Set KRAKEN_MASTER_API_KEY and KRAKEN_MASTER_API_SECRET")
            logger.error("      - Ensure account has at least $0.50 balance")
        if not copy_enabled:
            logger.error("   ⚠️  Copy trading is in OBSERVE MODE")
            logger.error("      - Change bot.py: start_copy_engine(observe_only=False)")
        logger.error("")
        logger.error("See documentation:")
        logger.error("   - KRAKEN_TRADING_FIX_JAN_20_2026.md")
        logger.error("   - KRAKEN_COPY_TRADING_README.md")
        logger.error("=" * 70)
        return 1

if __name__ == "__main__":
    sys.exit(main())
