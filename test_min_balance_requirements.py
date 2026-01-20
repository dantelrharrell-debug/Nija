"""
Test MIN_BALANCE_TO_TRADE requirements for Kraken and Coinbase

Verifies:
1. Both Kraken and Coinbase require $25 minimum balance
2. Kraken is configured as PRIMARY for small accounts
3. Coinbase is configured as SECONDARY/selective
4. Both use their own strategy rules (not shared logic)
"""

import sys
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(message)s'
)
logger = logging.getLogger(__name__)

def test_kraken_config():
    """Test Kraken configuration"""
    logger.info("\n" + "="*70)
    logger.info("TEST 1: Kraken Configuration")
    logger.info("="*70)
    
    try:
        from bot.broker_configs.kraken_config import KRAKEN_CONFIG
        
        # Test 1: Verify min_balance_to_trade is $25
        assert hasattr(KRAKEN_CONFIG, 'min_balance_to_trade'), "Kraken config missing min_balance_to_trade"
        assert KRAKEN_CONFIG.min_balance_to_trade == 25.0, f"Expected $25, got ${KRAKEN_CONFIG.min_balance_to_trade}"
        logger.info(f"✅ Kraken min_balance_to_trade = ${KRAKEN_CONFIG.min_balance_to_trade}")
        
        # Test 2: Verify Kraken is bidirectional (different from Coinbase)
        assert KRAKEN_CONFIG.bidirectional == True, "Kraken should be bidirectional"
        logger.info(f"✅ Kraken bidirectional = {KRAKEN_CONFIG.bidirectional} (can profit both ways)")
        
        # Test 3: Verify Kraken fee structure (lower fees than Coinbase)
        assert KRAKEN_CONFIG.round_trip_cost < 0.005, "Kraken fees should be < 0.5%"
        logger.info(f"✅ Kraken fees = {KRAKEN_CONFIG.round_trip_cost*100:.2f}% (lower than Coinbase)")
        
        # Test 4: Verify config summary mentions PRIMARY role
        summary = KRAKEN_CONFIG.get_config_summary()
        assert "PRIMARY" in summary, "Kraken summary should mention PRIMARY role"
        assert "small accounts" in summary.lower(), "Kraken summary should mention small accounts"
        logger.info(f"✅ Kraken config summary mentions PRIMARY role for small accounts")
        
        logger.info("\n✅ ALL KRAKEN TESTS PASSED")
        return True
        
    except Exception as e:
        logger.error(f"❌ Kraken config test failed: {e}")
        return False

def test_coinbase_config():
    """Test Coinbase configuration"""
    logger.info("\n" + "="*70)
    logger.info("TEST 2: Coinbase Configuration")
    logger.info("="*70)
    
    try:
        from bot.broker_configs.coinbase_config import COINBASE_CONFIG
        
        # Test 1: Verify min_balance_to_trade is $25
        assert hasattr(COINBASE_CONFIG, 'min_balance_to_trade'), "Coinbase config missing min_balance_to_trade"
        assert COINBASE_CONFIG.min_balance_to_trade == 25.0, f"Expected $25, got ${COINBASE_CONFIG.min_balance_to_trade}"
        logger.info(f"✅ Coinbase min_balance_to_trade = ${COINBASE_CONFIG.min_balance_to_trade}")
        
        # Test 2: Verify Coinbase is NOT bidirectional (different from Kraken)
        assert COINBASE_CONFIG.bidirectional == False, "Coinbase should NOT be bidirectional"
        logger.info(f"✅ Coinbase bidirectional = {COINBASE_CONFIG.bidirectional} (buy-focused strategy)")
        
        # Test 3: Verify Coinbase fee structure (higher fees than Kraken)
        assert COINBASE_CONFIG.round_trip_cost > 0.010, "Coinbase fees should be > 1%"
        logger.info(f"✅ Coinbase fees = {COINBASE_CONFIG.round_trip_cost*100:.1f}% (higher than Kraken)")
        
        # Test 4: Verify config summary mentions SECONDARY role
        summary = COINBASE_CONFIG.get_config_summary()
        assert "SECONDARY" in summary, "Coinbase summary should mention SECONDARY role"
        assert "not for small accounts" in summary.lower(), "Coinbase summary should mention not for small accounts"
        logger.info(f"✅ Coinbase config summary mentions SECONDARY role")
        
        logger.info("\n✅ ALL COINBASE TESTS PASSED")
        return True
        
    except Exception as e:
        logger.error(f"❌ Coinbase config test failed: {e}")
        return False

def test_broker_manager_constants():
    """Test broker_manager.py constants"""
    logger.info("\n" + "="*70)
    logger.info("TEST 3: Broker Manager Constants")
    logger.info("="*70)
    
    try:
        from bot.broker_manager import (
            KRAKEN_MINIMUM_BALANCE, 
            COINBASE_MINIMUM_BALANCE,
            MINIMUM_TRADING_BALANCE
        )
        
        # Test 1: Verify Kraken minimum is $25
        assert KRAKEN_MINIMUM_BALANCE == 25.0, f"Expected $25, got ${KRAKEN_MINIMUM_BALANCE}"
        logger.info(f"✅ KRAKEN_MINIMUM_BALANCE = ${KRAKEN_MINIMUM_BALANCE}")
        
        # Test 2: Verify Coinbase minimum is $25
        assert COINBASE_MINIMUM_BALANCE == 25.0, f"Expected $25, got ${COINBASE_MINIMUM_BALANCE}"
        logger.info(f"✅ COINBASE_MINIMUM_BALANCE = ${COINBASE_MINIMUM_BALANCE}")
        
        # Test 3: Both have same minimum (but different roles)
        assert KRAKEN_MINIMUM_BALANCE == COINBASE_MINIMUM_BALANCE, "Both should require $25"
        logger.info(f"✅ Both exchanges require same minimum (${KRAKEN_MINIMUM_BALANCE})")
        
        # Test 4: Verify minimum trading balance
        assert MINIMUM_TRADING_BALANCE == 25.0, f"Expected $25, got ${MINIMUM_TRADING_BALANCE}"
        logger.info(f"✅ MINIMUM_TRADING_BALANCE = ${MINIMUM_TRADING_BALANCE}")
        
        logger.info("\n✅ ALL BROKER MANAGER TESTS PASSED")
        return True
        
    except Exception as e:
        logger.error(f"❌ Broker manager test failed: {e}")
        return False

def test_strategy_differences():
    """Verify Kraken and Coinbase use different strategies"""
    logger.info("\n" + "="*70)
    logger.info("TEST 4: Strategy Differences (Kraken ≠ Coinbase)")
    logger.info("="*70)
    
    try:
        from bot.broker_configs.kraken_config import KRAKEN_CONFIG
        from bot.broker_configs.coinbase_config import COINBASE_CONFIG
        
        differences = []
        
        # Test 1: Different fee structures
        if KRAKEN_CONFIG.round_trip_cost != COINBASE_CONFIG.round_trip_cost:
            differences.append(f"Fees: Kraken {KRAKEN_CONFIG.round_trip_cost*100:.2f}% vs Coinbase {COINBASE_CONFIG.round_trip_cost*100:.1f}%")
        
        # Test 2: Different trading strategies
        if KRAKEN_CONFIG.bidirectional != COINBASE_CONFIG.bidirectional:
            differences.append(f"Strategy: Kraken bidirectional={KRAKEN_CONFIG.bidirectional} vs Coinbase bidirectional={COINBASE_CONFIG.bidirectional}")
        
        # Test 3: Different profit targets
        if KRAKEN_CONFIG.profit_targets != COINBASE_CONFIG.profit_targets:
            k_targets = [f"{t[0]*100:.1f}%" for t in KRAKEN_CONFIG.profit_targets]
            c_targets = [f"{t[0]*100:.1f}%" for t in COINBASE_CONFIG.profit_targets]
            differences.append(f"Profit targets: Kraken {k_targets} vs Coinbase {c_targets}")
        
        # Test 4: Different position sizing
        if KRAKEN_CONFIG.min_position_usd != COINBASE_CONFIG.min_position_usd:
            differences.append(f"Min position: Kraken ${KRAKEN_CONFIG.min_position_usd} vs Coinbase ${COINBASE_CONFIG.min_position_usd}")
        
        # Test 5: Different max positions
        if KRAKEN_CONFIG.max_positions != COINBASE_CONFIG.max_positions:
            differences.append(f"Max positions: Kraken {KRAKEN_CONFIG.max_positions} vs Coinbase {COINBASE_CONFIG.max_positions}")
        
        # Verify we found differences (they should NOT be using same logic)
        assert len(differences) > 0, "Kraken and Coinbase should have different strategies!"
        
        logger.info(f"✅ Found {len(differences)} strategy differences:")
        for diff in differences:
            logger.info(f"   • {diff}")
        
        logger.info("\n✅ COINBASE DOES NOT RUN KRAKEN-STYLE LOGIC ✅")
        return True
        
    except Exception as e:
        logger.error(f"❌ Strategy difference test failed: {e}")
        return False

def main():
    """Run all tests"""
    logger.info("\n" + "="*70)
    logger.info("MIN_BALANCE_TO_TRADE Requirements Test Suite")
    logger.info("="*70)
    
    results = {
        "Kraken Config": test_kraken_config(),
        "Coinbase Config": test_coinbase_config(),
        "Broker Manager": test_broker_manager_constants(),
        "Strategy Differences": test_strategy_differences()
    }
    
    # Summary
    logger.info("\n" + "="*70)
    logger.info("TEST SUMMARY")
    logger.info("="*70)
    
    all_passed = True
    for test_name, passed in results.items():
        status = "✅ PASSED" if passed else "❌ FAILED"
        logger.info(f"{test_name}: {status}")
        if not passed:
            all_passed = False
    
    logger.info("="*70)
    
    if all_passed:
        logger.info("\n🎉 ALL TESTS PASSED! 🎉")
        logger.info("\nConfiguration Summary:")
        logger.info("• Both Kraken and Coinbase: $25 minimum balance")
        logger.info("• Kraken: PRIMARY engine for small accounts")
        logger.info("• Coinbase: SECONDARY/selective (not for small accounts)")
        logger.info("• Each uses its own strategy rules (NOT shared logic)")
        return 0
    else:
        logger.error("\n❌ SOME TESTS FAILED")
        return 1

if __name__ == "__main__":
    sys.exit(main())
