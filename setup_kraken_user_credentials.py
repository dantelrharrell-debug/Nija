#!/usr/bin/env python3
"""
Setup Kraken User Credentials
Configures Daivon and Tania's Kraken API credentials and tests connections.
"""

import os
import sys
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s'
)
logger = logging.getLogger(__name__)

def set_credentials():
    """Set the Kraken credentials as environment variables."""
    
    # Daivon's credentials
    os.environ['KRAKEN_USER_DAIVON_API_KEY'] = 'HSo/f1zjeQALCM/rri9bjTB5JisQ/SPgurCRTx8W7kLD7psjcv2PXEf+'
    os.environ['KRAKEN_USER_DAIVON_API_SECRET'] = '6WOxnBLq+r4ln2Zz7nT0Nvv8CMkaolHtjYdOgTm7NWIq/mJqV8KbDA2XaThP65bHK9QvpEabRr1u38FrBJntaQ=='
    
    # Tania's credentials
    os.environ['KRAKEN_USER_TANIA_API_KEY'] = 'XEB37FsbsQ2Wj/bknOy6HPZTFqs25nyU10M2oxF/ja//Yh/r2kSRCAp/'
    os.environ['KRAKEN_USER_TANIA_API_SECRET'] = 'iINPAKFyVe9rTfYCKnauFCpOfqdsm9+lBFxzx2KLFkArjStbjAQ9Rr+FuA5lZgnzpZ85wMwnzKpkO07iHmMLmw=='
    
    logger.info("✅ Credentials loaded into environment")

def test_connections():
    """Test connections to Kraken for both users."""
    from bot.broker_manager import KrakenBroker, AccountType
    
    logger.info("=" * 80)
    logger.info("Testing Kraken Connections")
    logger.info("=" * 80)
    
    results = {}
    
    # Test Daivon's connection
    logger.info("\n📊 Testing Daivon Frazier's account...")
    try:
        daivon_broker = KrakenBroker(account_type=AccountType.USER, user_id='daivon_frazier')
        if daivon_broker.connect():
            balance = daivon_broker.get_account_balance()
            logger.info(f"✅ Daivon Frazier connected successfully")
            logger.info(f"   💰 Balance: ${balance.get('trading_balance', 0):.2f}")
            results['daivon'] = True
        else:
            logger.error("❌ Daivon Frazier connection failed")
            results['daivon'] = False
    except Exception as e:
        logger.error(f"❌ Daivon Frazier error: {e}")
        results['daivon'] = False
    
    # Test Tania's connection
    logger.info("\n📊 Testing Tania Gilbert's account...")
    try:
        tania_broker = KrakenBroker(account_type=AccountType.USER, user_id='tania_gilbert')
        if tania_broker.connect():
            balance = tania_broker.get_account_balance()
            logger.info(f"✅ Tania Gilbert connected successfully")
            logger.info(f"   💰 Balance: ${balance.get('trading_balance', 0):.2f}")
            results['tania'] = True
        else:
            logger.error("❌ Tania Gilbert connection failed")
            results['tania'] = False
    except Exception as e:
        logger.error(f"❌ Tania Gilbert error: {e}")
        results['tania'] = False
    
    return results

def main():
    """Main setup and test function."""
    logger.info("=" * 80)
    logger.info("  KRAKEN USER CREDENTIALS SETUP")
    logger.info("=" * 80)
    logger.info("")
    
    # Set credentials
    set_credentials()
    
    # Test connections
    results = test_connections()
    
    # Summary
    logger.info("\n" + "=" * 80)
    logger.info("  RESULTS")
    logger.info("=" * 80)
    
    success_count = sum(1 for v in results.values() if v)
    total_count = len(results)
    
    logger.info(f"\n  Connected accounts: {success_count}/{total_count}")
    logger.info("")
    
    for user, success in results.items():
        status = "✅ TRADING" if success else "❌ FAILED"
        logger.info(f"  {user.title()}: {status}")
    
    logger.info("")
    
    if success_count == total_count:
        logger.info("✅ ALL USERS READY TO TRADE!")
        logger.info("")
        logger.info("Next steps:")
        logger.info("  1. Add these credentials to Railway/Render environment variables")
        logger.info("  2. Restart your deployment")
        logger.info("  3. Verify trading starts automatically")
        logger.info("")
        return 0
    else:
        logger.error("❌ SOME CONNECTIONS FAILED")
        logger.error("")
        logger.error("Check the error messages above for details.")
        logger.error("Common issues:")
        logger.error("  • Invalid API key format")
        logger.error("  • Missing permissions on Kraken")
        logger.error("  • API rate limiting")
        logger.error("")
        return 1

if __name__ == "__main__":
    try:
        exit_code = main()
        sys.exit(exit_code)
    except KeyboardInterrupt:
        logger.info("\n\nSetup interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"\n\nUnexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
