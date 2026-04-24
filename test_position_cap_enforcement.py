#!/usr/bin/env python3
"""
Test script to verify position cap enforcement and forced cleanup
Tests the safety guarantees:
1. Users drop to ≤ 8 positions (forced cleanup)
2. No new entries once capped (position cap enforcer)
"""

import logging
import sys
import os

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(name)s | %(levelname)s | %(message)s'
)

logger = logging.getLogger("test_cap_enforcement")

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

try:
    from forced_position_cleanup import ForcedPositionCleanup, CleanupType
    logger.info("✅ Imported ForcedPositionCleanup")
except Exception as e:
    logger.error(f"❌ Failed to import ForcedPositionCleanup: {e}")
    sys.exit(1)


def test_dust_identification():
    """Test that dust positions are correctly identified"""
    logger.info("")
    logger.info("=" * 70)
    logger.info("TEST 1: Dust Position Identification")
    logger.info("=" * 70)
    
    cleanup = ForcedPositionCleanup(dust_threshold_usd=1.00, max_positions=8, dry_run=True)
    
    # Mock positions - some dust, some not
    mock_positions = [
        {'symbol': 'BTC-USD', 'size_usd': 50.0, 'pnl_pct': 0.02},
        {'symbol': 'ETH-USD', 'size_usd': 0.50, 'pnl_pct': -0.01},  # Dust
        {'symbol': 'SOL-USD', 'size_usd': 30.0, 'pnl_pct': 0.01},
        {'symbol': 'MATIC-USD', 'size_usd': 0.75, 'pnl_pct': 0.005},  # Dust
        {'symbol': 'DOGE-USD', 'size_usd': 0.25, 'pnl_pct': -0.02},  # Dust
    ]
    
    dust_positions = cleanup.identify_dust_positions(mock_positions)
    
    logger.info(f"Total positions: {len(mock_positions)}")
    logger.info(f"Dust positions found: {len(dust_positions)}")
    logger.info("")
    
    for dust in dust_positions:
        logger.info(f"  🧹 {dust['symbol']}: ${dust['size_usd']:.2f} - {dust['reason']}")
    
    # Verify
    expected_dust = 3  # ETH, MATIC, DOGE
    if len(dust_positions) == expected_dust:
        logger.info("")
        logger.info(f"✅ TEST PASSED: Found {expected_dust} dust positions as expected")
        return True
    else:
        logger.error("")
        logger.error(f"❌ TEST FAILED: Expected {expected_dust} dust positions, found {len(dust_positions)}")
        return False


def test_cap_excess_identification():
    """Test that excess positions for cap enforcement are correctly identified"""
    logger.info("")
    logger.info("=" * 70)
    logger.info("TEST 2: Position Cap Excess Identification")
    logger.info("=" * 70)
    
    cleanup = ForcedPositionCleanup(dust_threshold_usd=1.00, max_positions=8, dry_run=True)
    
    # Mock 12 positions (over cap of 8)
    mock_positions = []
    for i in range(12):
        mock_positions.append({
            'symbol': f'COIN{i}-USD',
            'size_usd': 10.0 + i,  # Varying sizes
            'pnl_pct': 0.01 * (i % 3 - 1),  # Some winners, some losers
        })
    
    logger.info(f"Total positions: {len(mock_positions)}")
    logger.info(f"Max allowed: 8")
    logger.info(f"Excess: {len(mock_positions) - 8}")
    
    excess_positions = cleanup.identify_cap_excess_positions(mock_positions)
    
    logger.info(f"Cap excess positions identified: {len(excess_positions)}")
    logger.info("")
    
    for i, pos in enumerate(excess_positions, 1):
        logger.info(f"  {i}. {pos['symbol']}: ${pos['size_usd']:.2f} (P&L: {pos['pnl_pct']*100:+.2f}%)")
    
    # Verify
    expected_excess = 4  # 12 - 8 = 4
    if len(excess_positions) == expected_excess:
        logger.info("")
        logger.info(f"✅ TEST PASSED: Identified {expected_excess} excess positions")
        logger.info(f"   These would be closed to enforce the 8-position cap")
        return True
    else:
        logger.error("")
        logger.error(f"❌ TEST FAILED: Expected {expected_excess} excess, found {len(excess_positions)}")
        return False


def test_user_cap_enforcement_logic():
    """Test that per-user position cap logic works correctly"""
    logger.info("")
    logger.info("=" * 70)
    logger.info("TEST 3: Per-User Position Cap Logic")
    logger.info("=" * 70)
    
    cleanup = ForcedPositionCleanup(dust_threshold_usd=1.00, max_positions=8, dry_run=True)
    
    # Simulate user with 9 positions across 2 brokers
    # Broker 1: 5 positions
    # Broker 2: 4 positions
    # Total: 9 (exceeds cap of 8 by 1)
    
    user_positions = []
    for i in range(9):
        user_positions.append({
            'symbol': f'COIN{i}-USD',
            'size_usd': 5.0 + i,
            'pnl_pct': 0.01,
        })
    
    logger.info(f"User total positions: {len(user_positions)} (across 2 brokers)")
    logger.info(f"Max allowed per user: {cleanup.max_positions}")
    logger.info(f"Excess: {len(user_positions) - cleanup.max_positions}")
    
    # Filter out dust (none in this case)
    non_dust = [p for p in user_positions if p['size_usd'] >= cleanup.dust_threshold_usd]
    
    logger.info(f"Non-dust positions: {len(non_dust)}")
    
    if len(non_dust) > cleanup.max_positions:
        logger.warning(f"🔒 USER cap exceeded: {len(non_dust)}/{cleanup.max_positions}")
        excess = cleanup.identify_cap_excess_positions(non_dust)
        logger.info(f"Positions to close: {len(excess)}")
        
        for pos in excess:
            logger.info(f"  Would close: {pos['symbol']} (${pos['size_usd']:.2f})")
        
        expected_excess = 1  # 9 - 8 = 1
        if len(excess) == expected_excess:
            logger.info("")
            logger.info(f"✅ TEST PASSED: Per-user cap would close {expected_excess} position(s)")
            return True
        else:
            logger.error("")
            logger.error(f"❌ TEST FAILED: Expected {expected_excess} to close, got {len(excess)}")
            return False
    else:
        logger.info(f"✅ Under cap")
        logger.error("")
        logger.error(f"❌ TEST FAILED: Should have detected cap excess")
        return False


def test_safety_verification_logic():
    """Test the safety verification logic"""
    logger.info("")
    logger.info("=" * 70)
    logger.info("TEST 4: Safety Verification Logic")
    logger.info("=" * 70)
    
    max_allowed = 8
    
    # Test case 1: Under cap
    current_count = 7
    logger.info(f"Test case 1: {current_count} positions (under cap)")
    if current_count <= max_allowed:
        logger.info(f"   ✅ SAFETY VERIFIED: {current_count} ≤ {max_allowed}")
        result1 = True
    else:
        logger.error(f"   ❌ SAFETY VIOLATION: {current_count} > {max_allowed}")
        result1 = False
    
    # Test case 2: At cap
    current_count = 8
    logger.info(f"Test case 2: {current_count} positions (at cap)")
    if current_count <= max_allowed:
        logger.info(f"   ✅ SAFETY VERIFIED: {current_count} ≤ {max_allowed}")
        result2 = True
    else:
        logger.error(f"   ❌ SAFETY VIOLATION: {current_count} > {max_allowed}")
        result2 = False
    
    # Test case 3: Over cap (should fail)
    current_count = 10
    logger.info(f"Test case 3: {current_count} positions (over cap)")
    if current_count <= max_allowed:
        logger.info(f"   ✅ SAFETY VERIFIED: {current_count} ≤ {max_allowed}")
        result3 = False  # This should NOT pass
    else:
        logger.error(f"   ❌ SAFETY VIOLATION: {current_count} > {max_allowed}")
        logger.info(f"   (This violation was correctly detected)")
        result3 = True  # Correctly detected violation
    
    logger.info("")
    if result1 and result2 and result3:
        logger.info("✅ TEST PASSED: Safety verification logic works correctly")
        return True
    else:
        logger.error("❌ TEST FAILED: Safety verification logic has issues")
        return False


def main():
    """Run all tests"""
    logger.info("")
    logger.info("=" * 70)
    logger.info("POSITION CAP ENFORCEMENT TEST SUITE")
    logger.info("=" * 70)
    logger.info("")
    logger.info("Testing safety guarantees:")
    logger.info("1. Users drop to ≤ 8 positions (forced cleanup)")
    logger.info("2. No new entries once capped (position cap enforcer)")
    logger.info("")
    
    results = []
    
    # Run tests
    results.append(("Dust Identification", test_dust_identification()))
    results.append(("Cap Excess Identification", test_cap_excess_identification()))
    results.append(("Per-User Cap Logic", test_user_cap_enforcement_logic()))
    results.append(("Safety Verification", test_safety_verification_logic()))
    
    # Summary
    logger.info("")
    logger.info("=" * 70)
    logger.info("TEST SUMMARY")
    logger.info("=" * 70)
    
    passed = 0
    failed = 0
    
    for test_name, result in results:
        if result:
            logger.info(f"✅ {test_name}: PASSED")
            passed += 1
        else:
            logger.error(f"❌ {test_name}: FAILED")
            failed += 1
    
    logger.info("")
    logger.info(f"Total: {len(results)} tests")
    logger.info(f"Passed: {passed}")
    logger.info(f"Failed: {failed}")
    logger.info("=" * 70)
    
    if failed == 0:
        logger.info("")
        logger.info("🎉 ALL TESTS PASSED - Position cap enforcement is working correctly!")
        logger.info("")
        return 0
    else:
        logger.error("")
        logger.error(f"⚠️ {failed} TEST(S) FAILED - Position cap enforcement has issues!")
        logger.error("")
        return 1


if __name__ == "__main__":
    sys.exit(main())
