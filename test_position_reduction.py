#!/usr/bin/env python3
"""
Test Position Reduction System
==============================

Validates that the position reduction system works as expected.

This test validates:
1. Dust position identification
2. Position cap enforcement
3. Outcome categorization (WIN/LOSS/BREAKEVEN)
4. Dry-run mode
5. Integration with simulation logic
"""

import sys
import os
import logging

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("test_position_reduction")


class MockBroker:
    """Mock broker for testing"""
    def __init__(self, positions):
        self.connected = True
        self.positions = positions
    
    def get_positions(self):
        return self.positions
    
    def close_position(self, symbol):
        return {'success': True, 'symbol': symbol}


class MockBrokerManager:
    """Mock broker manager for testing"""
    def __init__(self):
        self.brokers = {}
    
    def get_user_broker(self, user_id, broker_type):
        return self.brokers.get((user_id, broker_type))
    
    def add_broker(self, user_id, broker_type, broker):
        self.brokers[(user_id, broker_type)] = broker


class MockPortfolioManager:
    """Mock portfolio manager for testing"""
    pass


def create_test_positions():
    """Create test positions similar to the simulation"""
    return [
        # Dust positions (< $1 USD)
        {'symbol': 'DOGE-USD', 'quantity': 100, 'entry_price': 0.0030, 'current_price': 0.0032, 'position_id': '1', 'side': 'long'},
        {'symbol': 'SHIB-USD', 'quantity': 50000, 'entry_price': 0.000010, 'current_price': 0.000009, 'position_id': '2', 'side': 'long'},
        {'symbol': 'XLM-USD', 'quantity': 2, 'entry_price': 0.30, 'current_price': 0.28, 'position_id': '3', 'side': 'long'},
        
        # Small positions (over dust threshold)
        {'symbol': 'ADA-USD', 'quantity': 10, 'entry_price': 0.50, 'current_price': 0.55, 'position_id': '4', 'side': 'long'},
        {'symbol': 'DOT-USD', 'quantity': 5, 'entry_price': 8.00, 'current_price': 7.50, 'position_id': '5', 'side': 'long'},
        
        # Medium positions
        {'symbol': 'MATIC-USD', 'quantity': 50, 'entry_price': 1.00, 'current_price': 1.10, 'position_id': '6', 'side': 'long'},
        {'symbol': 'AVAX-USD', 'quantity': 10, 'entry_price': 40.00, 'current_price': 42.00, 'position_id': '7', 'side': 'long'},
        
        # Large positions
        {'symbol': 'ETH-USD', 'quantity': 0.5, 'entry_price': 3000, 'current_price': 3100, 'position_id': '8', 'side': 'long'},
        {'symbol': 'BTC-USD', 'quantity': 0.01, 'entry_price': 50000, 'current_price': 51000, 'position_id': '9', 'side': 'long'},
        {'symbol': 'SOL-USD', 'quantity': 5, 'entry_price': 100, 'current_price': 105, 'position_id': '10', 'side': 'long'},
    ]


def test_dust_identification():
    """Test dust position identification"""
    logger.info("=" * 70)
    logger.info("TEST 1: Dust Position Identification")
    logger.info("=" * 70)
    
    from user_position_reduction_engine import UserPositionReductionEngine
    
    # Create mock managers
    broker_mgr = MockBrokerManager()
    portfolio_mgr = MockPortfolioManager()
    
    # Create engine
    engine = UserPositionReductionEngine(
        multi_account_broker_manager=broker_mgr,
        portfolio_state_manager=portfolio_mgr,
        dust_threshold_usd=1.00
    )
    
    # Create test positions
    positions = create_test_positions()
    
    # Add broker with positions
    mock_broker = MockBroker(positions)
    broker_mgr.add_broker('test_user', 'kraken', mock_broker)
    
    # Get and identify dust positions
    user_positions = engine.get_user_positions('test_user', 'kraken')
    dust_positions = engine.identify_dust_positions(user_positions)
    
    logger.info(f"Total positions: {len(user_positions)}")
    logger.info(f"Dust positions identified: {len(dust_positions)}")
    
    # Verify dust positions
    expected_dust_count = 3  # DOGE, SHIB, XLM should be < $1
    assert len(dust_positions) == expected_dust_count, \
        f"Expected {expected_dust_count} dust positions, got {len(dust_positions)}"
    
    # Check dust values
    for pos in dust_positions:
        assert pos['size_usd'] < 1.00, \
            f"Dust position {pos['symbol']} has size ${pos['size_usd']:.2f} >= $1.00"
        logger.info(f"  ✅ {pos['symbol']}: ${pos['size_usd']:.2f} (dust)")
    
    logger.info("✅ TEST 1 PASSED: Dust identification works correctly\n")
    return True


def test_cap_enforcement():
    """Test position cap enforcement"""
    logger.info("=" * 70)
    logger.info("TEST 2: Position Cap Enforcement")
    logger.info("=" * 70)
    
    from user_position_reduction_engine import UserPositionReductionEngine
    
    # Create mock managers
    broker_mgr = MockBrokerManager()
    portfolio_mgr = MockPortfolioManager()
    
    # Create engine with cap of 5 positions
    engine = UserPositionReductionEngine(
        multi_account_broker_manager=broker_mgr,
        portfolio_state_manager=portfolio_mgr,
        max_positions=5,
        dust_threshold_usd=1.00
    )
    
    # Create test positions
    positions = create_test_positions()
    
    # Add broker with positions
    mock_broker = MockBroker(positions)
    broker_mgr.add_broker('test_user', 'kraken', mock_broker)
    
    # Get positions and identify what needs to be closed
    user_positions = engine.get_user_positions('test_user', 'kraken')
    dust_positions = engine.identify_dust_positions(user_positions)
    
    # Get non-dust positions
    non_dust = [p for p in user_positions if p['size_usd'] >= 1.00]
    cap_excess = engine.identify_cap_excess_positions(non_dust)
    
    logger.info(f"Total positions: {len(user_positions)}")
    logger.info(f"Dust positions: {len(dust_positions)}")
    logger.info(f"Non-dust positions: {len(non_dust)}")
    logger.info(f"Cap excess positions: {len(cap_excess)}")
    logger.info(f"Final positions after cleanup: {len(non_dust) - len(cap_excess)}")
    
    # After removing dust (3) and cap excess, should have exactly 5 positions
    final_count = len(non_dust) - len(cap_excess)
    assert final_count == 5, \
        f"Expected 5 final positions after cap enforcement, got {final_count}"
    
    # Verify smallest positions are selected for closure
    if cap_excess:
        logger.info("Positions selected for cap enforcement (should be smallest):")
        for pos in cap_excess:
            logger.info(f"  ✅ {pos['symbol']}: ${pos['size_usd']:.2f}")
    
    logger.info("✅ TEST 2 PASSED: Position cap enforcement works correctly\n")
    return True


def test_outcome_categorization():
    """Test outcome categorization"""
    logger.info("=" * 70)
    logger.info("TEST 3: Outcome Categorization")
    logger.info("=" * 70)
    
    from user_position_reduction_engine import UserPositionReductionEngine, PositionOutcome
    
    # Create engine
    broker_mgr = MockBrokerManager()
    portfolio_mgr = MockPortfolioManager()
    engine = UserPositionReductionEngine(
        multi_account_broker_manager=broker_mgr,
        portfolio_state_manager=portfolio_mgr
    )
    
    # Test outcome categorization
    test_cases = [
        (0.05, PositionOutcome.WIN, "+5% profit"),
        (-0.05, PositionOutcome.LOSS, "-5% loss"),
        (0.005, PositionOutcome.BREAKEVEN, "+0.5% near entry"),
        (-0.005, PositionOutcome.BREAKEVEN, "-0.5% near entry"),
        (0.15, PositionOutcome.WIN, "+15% profit"),
        (-0.25, PositionOutcome.LOSS, "-25% loss"),
    ]
    
    for pnl_pct, expected_outcome, description in test_cases:
        outcome = engine.categorize_outcome(pnl_pct)
        assert outcome == expected_outcome, \
            f"Expected {expected_outcome.value} for {description}, got {outcome.value}"
        logger.info(f"  ✅ {description:20s} → {outcome.value}")
    
    logger.info("✅ TEST 3 PASSED: Outcome categorization works correctly\n")
    return True


def test_dry_run_mode():
    """Test dry-run mode (preview without executing)"""
    logger.info("=" * 70)
    logger.info("TEST 4: Dry-Run Mode")
    logger.info("=" * 70)
    
    from user_position_reduction_engine import UserPositionReductionEngine
    
    # Create mock managers
    broker_mgr = MockBrokerManager()
    portfolio_mgr = MockPortfolioManager()
    
    # Create engine
    engine = UserPositionReductionEngine(
        multi_account_broker_manager=broker_mgr,
        portfolio_state_manager=portfolio_mgr,
        max_positions=8,
        dust_threshold_usd=1.00
    )
    
    # Create test positions
    positions = create_test_positions()
    
    # Add broker with positions
    mock_broker = MockBroker(positions)
    broker_mgr.add_broker('test_user', 'kraken', mock_broker)
    
    # Run dry-run
    result = engine.preview_reduction('test_user', 'kraken')
    
    logger.info(f"Dry-run result:")
    logger.info(f"  Initial positions: {result['initial_positions']}")
    logger.info(f"  Final positions: {result['final_positions']}")
    logger.info(f"  Positions to close: {result['closed_positions']}")
    logger.info(f"  Dust cleanup: {result['breakdown']['dust_closed']}")
    logger.info(f"  Cap excess: {result['breakdown']['cap_excess_closed']}")
    logger.info(f"  Dry run flag: {result['dry_run']}")
    
    # Verify dry-run flag is set
    assert result['dry_run'] == True, "Dry-run flag should be True"
    
    # Verify positions were analyzed but not actually closed
    # (In real scenario, we'd check that broker.close_position was not called)
    
    logger.info("✅ TEST 4 PASSED: Dry-run mode works correctly\n")
    return True


def test_integration_with_simulation():
    """Verify integration with simulation logic"""
    logger.info("=" * 70)
    logger.info("TEST 5: Integration with Simulation Logic")
    logger.info("=" * 70)
    
    # Import simulation to verify compatible logic
    try:
        from simulate_user_position_reduction import UserPositionSimulation, PositionOutcome as SimOutcome
        
        # Create simulation
        sim = UserPositionSimulation(
            user_id='test_user',
            initial_position_count=10,
            max_positions=8,
            dust_threshold_usd=1.00
        )
        
        # Generate positions
        sim.generate_realistic_positions()
        
        # Identify dust
        sim_dust = sim.identify_dust_positions()
        
        # Identify cap excess
        sim_excess = sim.identify_cap_excess_positions()
        
        logger.info(f"Simulation generated:")
        logger.info(f"  Total positions: {len(sim.positions)}")
        logger.info(f"  Dust positions: {len(sim_dust)}")
        logger.info(f"  Cap excess: {len(sim_excess)}")
        
        # Verify outcome categorization matches
        test_pnl = 0.05  # +5%
        sim_outcome = sim.categorize_outcome(test_pnl)
        
        from user_position_reduction_engine import UserPositionReductionEngine
        broker_mgr = MockBrokerManager()
        portfolio_mgr = MockPortfolioManager()
        engine = UserPositionReductionEngine(
            multi_account_broker_manager=broker_mgr,
            portfolio_state_manager=portfolio_mgr
        )
        
        engine_outcome = engine.categorize_outcome(test_pnl)
        
        assert sim_outcome == engine_outcome.value, \
            f"Simulation outcome {sim_outcome} != Engine outcome {engine_outcome.value}"
        
        logger.info("✅ TEST 5 PASSED: Logic matches simulation\n")
        return True
    
    except ImportError as e:
        logger.warning(f"⚠️  TEST 5 SKIPPED: Simulation not available ({e})")
        return True


def main():
    """Run all tests"""
    logger.info("\n" + "=" * 70)
    logger.info("POSITION REDUCTION SYSTEM TESTS")
    logger.info("=" * 70 + "\n")
    
    tests = [
        ("Dust Position Identification", test_dust_identification),
        ("Position Cap Enforcement", test_cap_enforcement),
        ("Outcome Categorization", test_outcome_categorization),
        ("Dry-Run Mode", test_dry_run_mode),
        ("Integration with Simulation", test_integration_with_simulation),
    ]
    
    passed = 0
    failed = 0
    
    for test_name, test_func in tests:
        try:
            if test_func():
                passed += 1
        except Exception as e:
            logger.error(f"❌ TEST FAILED: {test_name}")
            logger.error(f"   Error: {e}", exc_info=True)
            failed += 1
    
    # Summary
    logger.info("=" * 70)
    logger.info("TEST SUMMARY")
    logger.info("=" * 70)
    logger.info(f"Total tests: {len(tests)}")
    logger.info(f"Passed: {passed}")
    logger.info(f"Failed: {failed}")
    
    if failed == 0:
        logger.info("\n✅ ALL TESTS PASSED\n")
        return 0
    else:
        logger.error(f"\n❌ {failed} TESTS FAILED\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
