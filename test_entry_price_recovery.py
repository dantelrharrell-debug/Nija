#!/usr/bin/env python3
"""
Test script for get_real_entry_price implementation.

This script tests the new get_real_entry_price method that retrieves
actual entry prices from Coinbase order history.
"""

import sys
import os
import logging

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

def test_get_real_entry_price():
    """Test the get_real_entry_price method"""
    try:
        from broker_manager import CoinbaseBroker, AccountType
        
        logger.info("Initializing CoinbaseBroker...")
        broker = CoinbaseBroker(account_type=AccountType.MASTER)
        
        logger.info("Connecting to Coinbase...")
        if not broker.connect():
            logger.error("Failed to connect to Coinbase")
            return False
        
        logger.info("✅ Connected to Coinbase successfully")
        
        # Test with a symbol that likely has recent trades (use BTC-USD as example)
        test_symbol = "BTC-USD"
        
        logger.info(f"\nTesting get_real_entry_price for {test_symbol}...")
        entry_price = broker.get_real_entry_price(test_symbol)
        
        if entry_price:
            logger.info(f"✅ Successfully retrieved entry price: ${entry_price:.2f}")
            return True
        else:
            logger.info(f"⚠️  No entry price found for {test_symbol} (no recent BUY orders)")
            logger.info("   This is expected if you haven't bought this asset recently")
            return True  # Not an error - just no recent buys
            
    except Exception as e:
        logger.error(f"❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_position_tracking_integration():
    """Test integration with position tracker"""
    try:
        from broker_manager import CoinbaseBroker, AccountType
        
        logger.info("\n" + "="*60)
        logger.info("Testing Position Tracking Integration")
        logger.info("="*60)
        
        broker = CoinbaseBroker(account_type=AccountType.MASTER)
        
        if not broker.connect():
            logger.error("Failed to connect to Coinbase")
            return False
        
        # Get current positions
        logger.info("\nFetching current positions...")
        positions = broker.get_positions()
        
        if not positions:
            logger.info("⚠️  No open positions found")
            return True
        
        logger.info(f"Found {len(positions)} open position(s)")
        
        # Test entry price recovery for each position
        for pos in positions[:3]:  # Test first 3 positions
            symbol = pos.get('symbol', '')
            quantity = pos.get('quantity', 0)
            
            if not symbol or quantity <= 0:
                continue
            
            logger.info(f"\nPosition: {symbol}")
            logger.info(f"  Quantity: {quantity}")
            
            # Try to get entry price
            entry_price = broker.get_real_entry_price(symbol)
            if entry_price:
                logger.info(f"  ✅ Entry price recovered: ${entry_price:.2f}")
                
                # Calculate estimated position value
                current_price = pos.get('current_price', 0)
                if current_price:
                    cost_basis = entry_price * quantity
                    current_value = current_price * quantity
                    pnl_pct = ((current_price - entry_price) / entry_price) * 100
                    logger.info(f"  Current price: ${current_price:.2f}")
                    logger.info(f"  P&L: {pnl_pct:+.2f}%")
            else:
                logger.info(f"  ⚠️  No entry price available (no recent BUY orders)")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Integration test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    logger.info("="*60)
    logger.info("Entry Price Recovery Test")
    logger.info("="*60)
    
    # Run basic test
    success1 = test_get_real_entry_price()
    
    # Run integration test
    success2 = test_position_tracking_integration()
    
    logger.info("\n" + "="*60)
    if success1 and success2:
        logger.info("✅ All tests passed!")
        sys.exit(0)
    else:
        logger.info("❌ Some tests failed")
        sys.exit(1)
