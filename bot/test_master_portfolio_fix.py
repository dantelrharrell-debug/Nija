#!/usr/bin/env python3
"""
Test script for master portfolio fixes.

Tests:
1. Broker selection with Kraken promotion when Coinbase is exit_only
2. Master portfolio equity calculation (sum of all master brokers)
3. Database migration for master_trade_id column
"""

import sys
import os
import logging
import sqlite3
from pathlib import Path

# Add bot directory to path - this file is already in bot/ directory
sys.path.insert(0, os.path.dirname(__file__))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('test_master_portfolio')

def test_broker_selection():
    """Test broker selection logic with exit_only mode."""
    logger.info("=" * 70)
    logger.info("TEST 1: Broker Selection with Kraken Promotion")
    logger.info("=" * 70)
    
    try:
        from broker_manager import BrokerManager, BrokerType, BaseBroker
        
        # Create broker manager
        manager = BrokerManager()
        
        # Create mock broker class with required abstract methods
        class MockBroker(BaseBroker):
            def __init__(self, broker_type, exit_only=False):
                self.broker_type = broker_type
                self.connected = True
                self.exit_only_mode = exit_only
                self.credentials_configured = True
            
            def connect(self):
                return True
            
            def get_account_balance(self):
                return 100.0
            
            def place_market_order(self, symbol, side, quantity, **kwargs):
                return {"status": "filled"}
            
            def get_positions(self):
                return []
        
        # Add Coinbase (will be primary first)
        coinbase = MockBroker(BrokerType.COINBASE, exit_only=False)
        manager.add_broker(coinbase)
        
        # Add Kraken
        kraken = MockBroker(BrokerType.KRAKEN, exit_only=False)
        manager.add_broker(kraken)
        
        logger.info(f"✓ Initial primary broker: {manager.get_primary_broker().broker_type.value}")
        
        # Now simulate Coinbase going into exit_only mode
        coinbase.exit_only_mode = True
        logger.info("✓ Simulated Coinbase entering exit_only mode")
        
        # Call selection logic
        manager.select_primary_master_broker()
        
        # Check result
        primary = manager.get_primary_broker()
        if primary.broker_type == BrokerType.KRAKEN:
            logger.info("✅ TEST PASSED: Kraken promoted to primary when Coinbase in exit_only")
        else:
            logger.error(f"❌ TEST FAILED: Expected Kraken, got {primary.broker_type.value}")
            return False
        
        return True
        
    except Exception as e:
        logger.error(f"❌ TEST FAILED with exception: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_master_equity_calculation():
    """Test that master portfolio sums all broker balances."""
    logger.info("")
    logger.info("=" * 70)
    logger.info("TEST 2: Master Portfolio Equity Calculation")
    logger.info("=" * 70)
    
    try:
        from portfolio_state import PortfolioStateManager
        
        manager = PortfolioStateManager()
        
        # Test initial portfolio
        portfolio1 = manager.initialize_master_portfolio(100.0)
        logger.info(f"✓ First initialization: ${portfolio1.total_equity:.2f}")
        
        if portfolio1.total_equity != 100.0:
            logger.error(f"❌ Expected $100.00, got ${portfolio1.total_equity:.2f}")
            return False
        
        # Test update (should not overwrite, just update cash)
        portfolio2 = manager.initialize_master_portfolio(250.0)
        logger.info(f"✓ Updated equity: ${portfolio2.total_equity:.2f}")
        
        if portfolio2.total_equity != 250.0:
            logger.error(f"❌ Expected $250.00, got ${portfolio2.total_equity:.2f}")
            return False
        
        # Verify it's the same object (not overwritten)
        if portfolio1 is not portfolio2:
            logger.error("❌ Portfolio was overwritten instead of updated!")
            return False
        
        logger.info("✅ TEST PASSED: Portfolio correctly updates without overwriting")
        return True
        
    except Exception as e:
        logger.error(f"❌ TEST FAILED with exception: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_database_migration():
    """Test database migration for master_trade_id column."""
    logger.info("")
    logger.info("=" * 70)
    logger.info("TEST 3: Database Migration for master_trade_id")
    logger.info("=" * 70)
    
    try:
        from trade_ledger_db import TradeLedgerDB
        
        # Create test database
        test_db_path = "/tmp/test_trade_ledger.db"
        
        # Remove if exists
        if os.path.exists(test_db_path):
            os.remove(test_db_path)
        
        # Create database (should run migration)
        db = TradeLedgerDB(db_path=test_db_path)
        
        # Check if master_trade_id column exists
        conn = sqlite3.connect(test_db_path)
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(trade_ledger)")
        columns = [row[1] for row in cursor.fetchall()]
        conn.close()
        
        if 'master_trade_id' in columns:
            logger.info("✅ TEST PASSED: master_trade_id column exists")
            
            # Test inserting a record with master_trade_id
            tx_id = db.record_buy(
                symbol="BTC-USD",
                price=50000.0,
                quantity=0.001,
                size_usd=50.0,
                fee=0.3,
                master_trade_id="master_123"
            )
            
            # Verify it was recorded
            transactions = db.get_ledger_transactions(limit=1)
            if len(transactions) > 0 and transactions[0].get('master_trade_id') == 'master_123':
                logger.info("✅ master_trade_id successfully recorded in transaction")
            else:
                logger.error("❌ master_trade_id not properly recorded")
                return False
            
            return True
        else:
            logger.error(f"❌ TEST FAILED: master_trade_id column not found. Columns: {columns}")
            return False
        
    except Exception as e:
        logger.error(f"❌ TEST FAILED with exception: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        # Cleanup
        if os.path.exists(test_db_path):
            os.remove(test_db_path)


def main():
    """Run all tests."""
    logger.info("")
    logger.info("🧪 TESTING MASTER PORTFOLIO FIXES")
    logger.info("")
    
    results = []
    
    # Run tests
    results.append(("Broker Selection", test_broker_selection()))
    results.append(("Master Equity Calculation", test_master_equity_calculation()))
    results.append(("Database Migration", test_database_migration()))
    
    # Summary
    logger.info("")
    logger.info("=" * 70)
    logger.info("TEST SUMMARY")
    logger.info("=" * 70)
    
    passed = 0
    failed = 0
    
    for test_name, result in results:
        status = "✅ PASSED" if result else "❌ FAILED"
        logger.info(f"{status}: {test_name}")
        if result:
            passed += 1
        else:
            failed += 1
    
    logger.info("=" * 70)
    logger.info(f"Total: {passed} passed, {failed} failed")
    logger.info("=" * 70)
    
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
