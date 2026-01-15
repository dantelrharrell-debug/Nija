#!/usr/bin/env python3
"""
Test script to debug balance detection issue.
This will help us understand why get_account_balance() returns 0.
"""

import os
import sys
import logging

# Setup paths
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

logger = logging.getLogger(__name__)

def test_coinbase_balance():
    """Test Coinbase balance fetching"""
    from broker_manager import CoinbaseBroker, BrokerType
    
    logger.info("=" * 70)
    logger.info("🧪 TESTING COINBASE BALANCE DETECTION")
    logger.info("=" * 70)
    
    # Create and connect to Coinbase
    logger.info("Creating CoinbaseBroker instance...")
    broker = CoinbaseBroker()
    
    logger.info("Connecting to Coinbase...")
    if not broker.connect():
        logger.error("❌ Failed to connect to Coinbase")
        return False
    
    logger.info("✅ Connected successfully")
    logger.info("")
    
    # Test 1: Call get_account_balance() immediately
    logger.info("TEST 1: Call get_account_balance() immediately after connection")
    balance1 = broker.get_account_balance()
    logger.info(f"   Result: ${balance1:.2f}")
    logger.info("")
    
    # Test 2: Wait 2 seconds and try again
    logger.info("TEST 2: Wait 2 seconds and try again")
    import time
    time.sleep(2.0)
    balance2 = broker.get_account_balance()
    logger.info(f"   Result: ${balance2:.2f}")
    logger.info("")
    
    # Test 3: Clear cache and try again
    logger.info("TEST 3: Clear balance cache and try again")
    broker.clear_cache()
    balance3 = broker.get_account_balance()
    logger.info(f"   Result: ${balance3:.2f}")
    logger.info("")
    
    # Test 4: Call _get_account_balance_detailed() directly
    logger.info("TEST 4: Call _get_account_balance_detailed() directly")
    broker.clear_cache()
    balance_data = broker._get_account_balance_detailed()
    if balance_data:
        logger.info(f"   USD: ${balance_data.get('usd', 0):.2f}")
        logger.info(f"   USDC: ${balance_data.get('usdc', 0):.2f}")
        logger.info(f"   Trading Balance: ${balance_data.get('trading_balance', 0):.2f}")
        logger.info(f"   Consumer USD: ${balance_data.get('consumer_usd', 0):.2f}")
        logger.info(f"   Consumer USDC: ${balance_data.get('consumer_usdc', 0):.2f}")
    else:
        logger.error("   ❌ _get_account_balance_detailed() returned None")
    
    logger.info("")
    logger.info("=" * 70)
    logger.info("🧪 TEST COMPLETE")
    logger.info("=" * 70)
    
    return True

if __name__ == "__main__":
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    
    test_coinbase_balance()
