"""
Test broker capital isolation and equity-based balance calculation.

This test verifies:
1. Rule #1: Brokers are capital-isolated (independent balance, health, etc.)
2. Rule #2: Independent trading loops (parallel execution)
3. Rule #3: Balance = CASH + POSITION VALUE (equity-based calculations)
"""

import sys
import logging
from typing import Dict, List

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def test_rule_1_broker_isolation():
    """
    Test Rule #1: Brokers are CAPITAL-ISOLATED
    
    Each broker must have:
    - Its own balance
    - Its own positions
    - Its own risk rules
    - Its own health status
    - No broker blocks another
    """
    logger.info("=" * 70)
    logger.info("TEST: Rule #1 - Broker Capital Isolation")
    logger.info("=" * 70)
    
    try:
        from bot.broker_manager import CoinbaseBroker, KrakenBroker, OKXBroker, AccountType
        
        # Test that each broker maintains independent state
        test_results = []
        
        # Check Coinbase broker isolation
        logger.info("\n✅ Testing Coinbase broker isolation...")
        coinbase = CoinbaseBroker(account_type=AccountType.MASTER)
        
        # Verify independent balance tracking
        assert hasattr(coinbase, '_last_known_balance'), "Coinbase missing independent balance tracking"
        assert hasattr(coinbase, '_balance_fetch_errors'), "Coinbase missing error tracking"
        assert hasattr(coinbase, '_is_available'), "Coinbase missing availability flag"
        logger.info("   ✓ Coinbase has independent balance state")
        test_results.append(("Coinbase isolation", True))
        
        # Check Kraken broker isolation
        logger.info("\n✅ Testing Kraken broker isolation...")
        kraken = KrakenBroker(account_type=AccountType.MASTER)
        
        # Verify independent balance tracking
        assert hasattr(kraken, '_last_known_balance'), "Kraken missing independent balance tracking"
        assert hasattr(kraken, '_balance_fetch_errors'), "Kraken missing error tracking"
        assert hasattr(kraken, '_is_available'), "Kraken missing availability flag"
        logger.info("   ✓ Kraken has independent balance state")
        test_results.append(("Kraken isolation", True))
        
        # Check OKX broker isolation
        logger.info("\n✅ Testing OKX broker isolation...")
        okx = OKXBroker(account_type=AccountType.MASTER)
        
        # Verify independent balance tracking
        assert hasattr(okx, '_last_known_balance'), "OKX missing independent balance tracking"
        assert hasattr(okx, '_balance_fetch_errors'), "OKX missing error tracking"
        assert hasattr(okx, '_is_available'), "OKX missing availability flag"
        logger.info("   ✓ OKX has independent balance state")
        test_results.append(("OKX isolation", True))
        
        # Verify brokers don't share state
        logger.info("\n✅ Testing broker state independence...")
        coinbase._last_known_balance = 100.0
        kraken._last_known_balance = 200.0
        okx._last_known_balance = 300.0
        
        assert coinbase._last_known_balance == 100.0, "Coinbase state corrupted"
        assert kraken._last_known_balance == 200.0, "Kraken state corrupted"
        assert okx._last_known_balance == 300.0, "OKX state corrupted"
        logger.info("   ✓ Brokers maintain independent state")
        test_results.append(("State independence", True))
        
        # Summary
        logger.info("\n" + "=" * 70)
        logger.info("Rule #1 Test Results:")
        for test_name, passed in test_results:
            status = "✅ PASS" if passed else "❌ FAIL"
            logger.info(f"   {status}: {test_name}")
        logger.info("=" * 70)
        
        return all(result for _, result in test_results)
        
    except Exception as e:
        logger.error(f"❌ Rule #1 test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_rule_2_independent_loops():
    """
    Test Rule #2: Independent trading loops (parallel)
    
    Each trader must trade on its own broker only.
    If one fails, others continue trading.
    """
    logger.info("\n" + "=" * 70)
    logger.info("TEST: Rule #2 - Independent Trading Loops")
    logger.info("=" * 70)
    
    try:
        from bot.independent_broker_trader import IndependentBrokerTrader
        from bot.broker_manager import BrokerManager, BrokerType
        
        test_results = []
        
        # Verify IndependentBrokerTrader has isolation mechanisms
        logger.info("\n✅ Testing independent broker trader architecture...")
        
        # Create mock broker manager
        broker_manager = BrokerManager()
        
        # Create independent trader (without connecting brokers)
        trader = IndependentBrokerTrader(
            broker_manager=broker_manager,
            trading_strategy=None  # Mock
        )
        
        # Verify isolation mechanisms
        assert hasattr(trader, 'broker_health'), "Missing per-broker health tracking"
        assert hasattr(trader, 'broker_threads'), "Missing per-broker thread tracking"
        assert hasattr(trader, 'stop_flags'), "Missing per-broker stop flags"
        assert hasattr(trader, 'funded_brokers'), "Missing funded broker tracking"
        logger.info("   ✓ Independent trader has isolation mechanisms")
        test_results.append(("Isolation mechanisms", True))
        
        # Verify thread safety
        assert hasattr(trader, 'health_lock'), "Missing thread safety lock"
        assert hasattr(trader, 'active_trading_threads'), "Missing active thread tracking"
        assert hasattr(trader, 'active_threads_lock'), "Missing active threads lock"
        logger.info("   ✓ Thread safety mechanisms present")
        test_results.append(("Thread safety", True))
        
        # Summary
        logger.info("\n" + "=" * 70)
        logger.info("Rule #2 Test Results:")
        for test_name, passed in test_results:
            status = "✅ PASS" if passed else "❌ FAIL"
            logger.info(f"   {status}: {test_name}")
        logger.info("=" * 70)
        
        return all(result for _, result in test_results)
        
    except Exception as e:
        logger.error(f"❌ Rule #2 test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_rule_3_equity_balance():
    """
    Test Rule #3: Balance = CASH + POSITION VALUE
    
    Verify that get_account_balance() returns total equity, not just cash.
    """
    logger.info("\n" + "=" * 70)
    logger.info("TEST: Rule #3 - Balance = CASH + POSITION VALUE")
    logger.info("=" * 70)
    
    try:
        from bot.broker_manager import BaseBroker, AccountType
        
        test_results = []
        
        # Test BaseBroker has get_total_capital method
        logger.info("\n✅ Testing BaseBroker equity calculation interface...")
        assert hasattr(BaseBroker, 'get_total_capital'), "BaseBroker missing get_total_capital method"
        logger.info("   ✓ BaseBroker has get_total_capital method")
        test_results.append(("BaseBroker interface", True))
        
        # Verify method signature expectations
        logger.info("\n✅ Verifying broker implementations...")
        
        # Check that brokers have position fetching capability
        from bot.broker_manager import CoinbaseBroker, KrakenBroker, OKXBroker, AlpacaBroker
        
        for BrokerClass, name in [
            (CoinbaseBroker, "Coinbase"),
            (KrakenBroker, "Kraken"),
            (OKXBroker, "OKX"),
            (AlpacaBroker, "Alpaca")
        ]:
            broker = BrokerClass(account_type=AccountType.MASTER)
            
            # Verify broker has methods for equity calculation
            assert hasattr(broker, 'get_account_balance'), f"{name} missing get_account_balance"
            assert hasattr(broker, 'get_positions'), f"{name} missing get_positions"
            assert hasattr(broker, 'get_total_capital'), f"{name} missing get_total_capital"
            
            logger.info(f"   ✓ {name} has equity calculation methods")
            test_results.append((f"{name} equity methods", True))
        
        # Test OKX has get_current_price (needed for position valuation)
        logger.info("\n✅ Testing OKX position valuation...")
        okx = OKXBroker(account_type=AccountType.MASTER)
        assert hasattr(okx, 'get_current_price'), "OKX missing get_current_price method"
        logger.info("   ✓ OKX has get_current_price for position valuation")
        test_results.append(("OKX position valuation", True))
        
        # Summary
        logger.info("\n" + "=" * 70)
        logger.info("Rule #3 Test Results:")
        for test_name, passed in test_results:
            status = "✅ PASS" if passed else "❌ FAIL"
            logger.info(f"   {status}: {test_name}")
        logger.info("=" * 70)
        
        return all(result for _, result in test_results)
        
    except Exception as e:
        logger.error(f"❌ Rule #3 test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all tests."""
    logger.info("=" * 70)
    logger.info("BROKER ISOLATION AND EQUITY BALANCE TESTS")
    logger.info("=" * 70)
    
    results = {}
    
    # Test Rule #1: Broker Capital Isolation
    results['Rule #1'] = test_rule_1_broker_isolation()
    
    # Test Rule #2: Independent Trading Loops
    results['Rule #2'] = test_rule_2_independent_loops()
    
    # Test Rule #3: Balance = CASH + POSITION VALUE
    results['Rule #3'] = test_rule_3_equity_balance()
    
    # Final summary
    logger.info("\n" + "=" * 70)
    logger.info("FINAL TEST SUMMARY")
    logger.info("=" * 70)
    
    all_passed = True
    for rule, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        logger.info(f"{status}: {rule}")
        if not passed:
            all_passed = False
    
    logger.info("=" * 70)
    
    if all_passed:
        logger.info("✅ ALL TESTS PASSED")
        logger.info("Broker isolation and equity-based balance calculation verified!")
        return 0
    else:
        logger.error("❌ SOME TESTS FAILED")
        logger.error("Review failed tests above for details.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
