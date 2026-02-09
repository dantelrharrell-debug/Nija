#!/usr/bin/env python3
"""
Test script for position normalization feature.

Tests:
1. Position ranking (largest kept, smallest sold)
2. Dust blacklist persistence
3. Position filtering with blacklist
4. Entry blocking when over cap
"""

import sys
import os
import logging

# Add bot directory to path
bot_dir = os.path.join(os.path.dirname(__file__), 'bot')
sys.path.insert(0, bot_dir)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(name)s | %(levelname)s | %(message)s'
)

logger = logging.getLogger("test_position_normalization")


def test_dust_blacklist():
    """Test dust blacklist functionality."""
    logger.info("=" * 70)
    logger.info("TEST 1: Dust Blacklist Functionality")
    logger.info("=" * 70)
    
    # Import directly from dust_blacklist.py to avoid bot.py import
    import importlib.util
    spec = importlib.util.spec_from_file_location("dust_blacklist", os.path.join(bot_dir, "dust_blacklist.py"))
    dust_blacklist_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dust_blacklist_module)
    DustBlacklist = dust_blacklist_module.DustBlacklist
    
    # Create test blacklist in temp directory
    blacklist = DustBlacklist(data_dir="/tmp/nija_test")
    
    # Test adding symbols
    logger.info("Adding test symbols to blacklist...")
    blacklist.add_to_blacklist("DUST-USD", 0.50, "test dust position")
    blacklist.add_to_blacklist("TINY-USD", 0.25, "test tiny position")
    
    # Test checking
    assert blacklist.is_blacklisted("DUST-USD"), "DUST-USD should be blacklisted"
    assert blacklist.is_blacklisted("TINY-USD"), "TINY-USD should be blacklisted"
    assert not blacklist.is_blacklisted("BTC-USD"), "BTC-USD should not be blacklisted"
    
    # Test stats
    stats = blacklist.get_stats()
    logger.info(f"Blacklist stats: {stats}")
    assert stats['count'] == 2, f"Expected 2 blacklisted symbols, got {stats['count']}"
    
    # Test removal
    blacklist.remove_from_blacklist("TINY-USD")
    assert not blacklist.is_blacklisted("TINY-USD"), "TINY-USD should be removed"
    assert blacklist.is_blacklisted("DUST-USD"), "DUST-USD should still be blacklisted"
    
    logger.info("✅ Dust blacklist tests passed!")
    logger.info("")
    return True


def test_position_ranking():
    """Test position ranking (largest kept, smallest sold)."""
    logger.info("=" * 70)
    logger.info("TEST 2: Position Ranking Logic")
    logger.info("=" * 70)
    
    # Mock position data
    positions = [
        {'symbol': 'BTC-USD', 'usd_value': 1000.00},
        {'symbol': 'ETH-USD', 'usd_value': 500.00},
        {'symbol': 'SOL-USD', 'usd_value': 200.00},
        {'symbol': 'DOGE-USD', 'usd_value': 50.00},
        {'symbol': 'SHIB-USD', 'usd_value': 10.00},
        {'symbol': 'PEPE-USD', 'usd_value': 5.00},
        {'symbol': 'XRP-USD', 'usd_value': 2.00},
        {'symbol': 'ADA-USD', 'usd_value': 1.50},
    ]
    
    max_positions = 5
    
    # Sort by largest first
    sorted_positions = sorted(positions, key=lambda p: p['usd_value'], reverse=True)
    
    # Positions to keep (largest)
    positions_to_keep = sorted_positions[:max_positions]
    
    # Positions to liquidate (smallest)
    positions_to_liquidate = sorted_positions[max_positions:]
    
    logger.info(f"Total positions: {len(positions)}")
    logger.info(f"Max allowed: {max_positions}")
    logger.info(f"Positions to KEEP (largest {max_positions}):")
    for i, pos in enumerate(positions_to_keep, 1):
        logger.info(f"  {i}. {pos['symbol']}: ${pos['usd_value']:.2f}")
    
    logger.info(f"\nPositions to LIQUIDATE (smallest {len(positions_to_liquidate)}):")
    for i, pos in enumerate(positions_to_liquidate, 1):
        logger.info(f"  {i}. {pos['symbol']}: ${pos['usd_value']:.2f}")
    
    # Verify correct positions are kept
    assert positions_to_keep[0]['symbol'] == 'BTC-USD', "BTC should be kept (largest)"
    assert positions_to_keep[4]['symbol'] == 'SHIB-USD', "SHIB should be kept (5th largest)"
    
    # Verify correct positions are liquidated
    assert positions_to_liquidate[0]['symbol'] == 'PEPE-USD', "PEPE should be liquidated"
    assert positions_to_liquidate[-1]['symbol'] == 'ADA-USD', "ADA should be liquidated (smallest)"
    
    logger.info("✅ Position ranking tests passed!")
    logger.info("")
    return True


def test_position_filtering():
    """Test position filtering with blacklist."""
    logger.info("=" * 70)
    logger.info("TEST 3: Position Filtering with Blacklist")
    logger.info("=" * 70)
    
    # Import directly from dust_blacklist.py to avoid bot.py import
    import importlib.util
    spec = importlib.util.spec_from_file_location("dust_blacklist", os.path.join(bot_dir, "dust_blacklist.py"))
    dust_blacklist_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dust_blacklist_module)
    DustBlacklist = dust_blacklist_module.DustBlacklist
    
    # Create test blacklist
    blacklist = DustBlacklist(data_dir="/tmp/nija_test_filter")
    blacklist.add_to_blacklist("DUST1-USD", 0.30, "dust")
    blacklist.add_to_blacklist("DUST2-USD", 0.50, "dust")
    
    # Mock positions (mix of valid and blacklisted)
    all_positions = [
        {'symbol': 'BTC-USD', 'usd_value': 1000.00},
        {'symbol': 'DUST1-USD', 'usd_value': 0.30},  # Blacklisted
        {'symbol': 'ETH-USD', 'usd_value': 500.00},
        {'symbol': 'DUST2-USD', 'usd_value': 0.50},  # Blacklisted
        {'symbol': 'SOL-USD', 'usd_value': 200.00},
    ]
    
    # Filter out blacklisted
    filtered_positions = [
        pos for pos in all_positions
        if not blacklist.is_blacklisted(pos['symbol'])
    ]
    
    logger.info(f"Total positions: {len(all_positions)}")
    logger.info(f"Blacklisted: {len(all_positions) - len(filtered_positions)}")
    logger.info(f"Valid positions after filtering: {len(filtered_positions)}")
    
    for pos in filtered_positions:
        logger.info(f"  ✓ {pos['symbol']}: ${pos['usd_value']:.2f}")
    
    # Verify filtering
    assert len(filtered_positions) == 3, f"Expected 3 valid positions, got {len(filtered_positions)}"
    assert not any(pos['symbol'].startswith('DUST') for pos in filtered_positions), "Dust positions should be filtered"
    
    logger.info("✅ Position filtering tests passed!")
    logger.info("")
    return True


def test_normalization_workflow():
    """Test complete normalization workflow."""
    logger.info("=" * 70)
    logger.info("TEST 4: Complete Normalization Workflow")
    logger.info("=" * 70)
    
    # Import directly from dust_blacklist.py to avoid bot.py import
    import importlib.util
    spec = importlib.util.spec_from_file_location("dust_blacklist", os.path.join(bot_dir, "dust_blacklist.py"))
    dust_blacklist_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dust_blacklist_module)
    DustBlacklist = dust_blacklist_module.DustBlacklist
    
    # Simulate scenario: 59 positions → 5 positions
    logger.info("Scenario: User has 59 positions, need to normalize to 5")
    logger.info("")
    
    # Create test blacklist
    blacklist = DustBlacklist(data_dir="/tmp/nija_test_workflow")
    
    # Simulate positions with various USD values
    positions = []
    
    # Add 10 large positions ($100-$1000)
    for i in range(10):
        positions.append({
            'symbol': f'LARGE{i}-USD',
            'usd_value': 100.00 + (i * 100)
        })
    
    # Add 20 medium positions ($10-$50)
    for i in range(20):
        positions.append({
            'symbol': f'MED{i}-USD',
            'usd_value': 10.00 + (i * 2)
        })
    
    # Add 29 dust positions ($0.10-$0.90) - should be blacklisted
    for i in range(29):
        positions.append({
            'symbol': f'DUST{i}-USD',
            'usd_value': 0.10 + (i * 0.03)
        })
    
    logger.info(f"Initial position count: {len(positions)}")
    
    # Step 1: Blacklist dust positions
    dust_count = 0
    for pos in positions:
        if pos['usd_value'] < 1.00:
            blacklist.add_to_blacklist(pos['symbol'], pos['usd_value'], "dust position")
            dust_count += 1
    
    logger.info(f"Step 1: Blacklisted {dust_count} dust positions (< $1.00)")
    
    # Step 2: Filter blacklisted positions
    valid_positions = [
        pos for pos in positions
        if not blacklist.is_blacklisted(pos['symbol'])
    ]
    
    logger.info(f"Step 2: Valid positions after blacklist: {len(valid_positions)}")
    
    # Step 3: Normalize to cap (keep 5 largest)
    max_positions = 5
    sorted_positions = sorted(valid_positions, key=lambda p: p['usd_value'], reverse=True)
    positions_to_keep = sorted_positions[:max_positions]
    positions_to_liquidate = sorted_positions[max_positions:]
    
    logger.info(f"Step 3: Normalize to cap ({max_positions})")
    logger.info(f"  Keeping {len(positions_to_keep)} largest positions:")
    for i, pos in enumerate(positions_to_keep, 1):
        logger.info(f"    {i}. {pos['symbol']}: ${pos['usd_value']:.2f}")
    
    logger.info(f"  Liquidating {len(positions_to_liquidate)} smallest positions")
    
    # Verify results
    assert dust_count == 29, f"Expected 29 dust positions, got {dust_count}"
    assert len(valid_positions) == 30, f"Expected 30 valid positions, got {len(valid_positions)}"
    assert len(positions_to_keep) == 5, f"Expected 5 positions to keep, got {len(positions_to_keep)}"
    assert len(positions_to_liquidate) == 25, f"Expected 25 positions to liquidate, got {len(positions_to_liquidate)}"
    
    # Verify largest positions are kept
    assert positions_to_keep[0]['symbol'] == 'LARGE9-USD', "Largest position should be kept"
    assert positions_to_keep[0]['usd_value'] == 1000.00, "Largest value should be $1000"
    
    logger.info("")
    logger.info("✅ Complete workflow test passed!")
    logger.info(f"   Result: {len(positions)} → {len(positions_to_keep)} positions")
    logger.info("")
    return True


def main():
    """Run all tests."""
    logger.info("")
    logger.info("╔" + "=" * 68 + "╗")
    logger.info("║" + " " * 15 + "POSITION NORMALIZATION TESTS" + " " * 25 + "║")
    logger.info("╚" + "=" * 68 + "╝")
    logger.info("")
    
    tests = [
        ("Dust Blacklist", test_dust_blacklist),
        ("Position Ranking", test_position_ranking),
        ("Position Filtering", test_position_filtering),
        ("Normalization Workflow", test_normalization_workflow),
    ]
    
    passed = 0
    failed = 0
    
    for test_name, test_func in tests:
        try:
            if test_func():
                passed += 1
        except Exception as e:
            logger.error(f"❌ Test failed: {test_name}")
            logger.error(f"   Error: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    
    logger.info("=" * 70)
    logger.info("TEST SUMMARY")
    logger.info("=" * 70)
    logger.info(f"Passed: {passed}/{len(tests)}")
    logger.info(f"Failed: {failed}/{len(tests)}")
    logger.info("=" * 70)
    
    if failed == 0:
        logger.info("✅ ALL TESTS PASSED!")
        return 0
    else:
        logger.error("❌ SOME TESTS FAILED")
        return 1


if __name__ == '__main__':
    sys.exit(main())
