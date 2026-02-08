#!/usr/bin/env python3
"""
Test script to verify forced cleanup configuration options work correctly
"""

import os
import sys

# Add parent directory to path for imports
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, parent_dir)

from forced_position_cleanup import ForcedPositionCleanup, CleanupType


def test_default_config():
    """Test default configuration (conservative mode)"""
    print("=" * 70)
    print("TEST 1: Default Configuration (Conservative Mode)")
    print("=" * 70)
    
    cleanup = ForcedPositionCleanup(
        dust_threshold_usd=1.00,
        max_positions=8,
        dry_run=True
    )
    
    assert cleanup.cancel_open_orders == False, "Default should not cancel open orders"
    assert cleanup.startup_only == False, "Default should not be startup-only"
    assert cleanup.cancel_conditions is None, "Default should have no conditions"
    
    print("✅ Default config is conservative (no open order cancellation)")
    print()


def test_nuclear_mode():
    """Test nuclear mode (startup-only cancellation)"""
    print("=" * 70)
    print("TEST 2: Nuclear Mode (Startup-Only)")
    print("=" * 70)
    
    cleanup = ForcedPositionCleanup(
        dust_threshold_usd=1.00,
        max_positions=8,
        dry_run=True,
        cancel_open_orders=True,
        startup_only=True
    )
    
    assert cleanup.cancel_open_orders == True, "Nuclear mode should cancel orders"
    assert cleanup.startup_only == True, "Nuclear mode should be startup-only"
    
    # Test startup decision
    test_pos = {
        'symbol': 'BTC-USD',
        'size_usd': 0.50,
        'cleanup_type': CleanupType.DUST.value
    }
    
    # Should cancel on startup
    should_cancel_startup = cleanup._should_cancel_open_orders(test_pos, is_startup=True)
    assert should_cancel_startup == True, "Should cancel on startup"
    
    # Mark startup as complete
    cleanup.has_run_startup = True
    
    # Should NOT cancel after startup
    should_cancel_after = cleanup._should_cancel_open_orders(test_pos, is_startup=False)
    assert should_cancel_after == False, "Should not cancel after startup"
    
    print("✅ Nuclear mode works correctly (startup-only)")
    print()


def test_selective_mode():
    """Test selective mode (conditional cancellation)"""
    print("=" * 70)
    print("TEST 3: Selective Mode (Conditional)")
    print("=" * 70)
    
    cleanup = ForcedPositionCleanup(
        dust_threshold_usd=1.00,
        max_positions=8,
        dry_run=True,
        cancel_conditions="usd_value<1.0,rank>max_positions"
    )
    
    assert cleanup.cancel_open_orders == True, "Selective mode should enable cancellation"
    assert cleanup.cancel_conditions is not None, "Should have conditions"
    assert 'usd_value' in cleanup.cancel_conditions, "Should parse usd_value condition"
    assert 'rank_exceeds_cap' in cleanup.cancel_conditions, "Should parse rank condition"
    
    # Test dust position (should cancel due to usd_value < 1.0)
    dust_pos = {
        'symbol': 'SHIB-USD',
        'size_usd': 0.50,
        'cleanup_type': CleanupType.DUST.value
    }
    should_cancel_dust = cleanup._should_cancel_open_orders(dust_pos, is_startup=False)
    assert should_cancel_dust == True, "Should cancel dust position (usd_value < 1.0)"
    
    # Test cap-exceeded position (should cancel due to rank)
    cap_pos = {
        'symbol': 'ATOM-USD',
        'size_usd': 5.00,
        'cleanup_type': CleanupType.CAP_EXCEEDED.value
    }
    should_cancel_cap = cleanup._should_cancel_open_orders(cap_pos, is_startup=False)
    assert should_cancel_cap == True, "Should cancel cap-exceeded position"
    
    # Test normal position (should NOT cancel)
    normal_pos = {
        'symbol': 'BTC-USD',
        'size_usd': 50.00,
        'cleanup_type': CleanupType.DUST.value  # Not really dust, just for test
    }
    should_cancel_normal = cleanup._should_cancel_open_orders(normal_pos, is_startup=False)
    assert should_cancel_normal == False, "Should not cancel normal position"
    
    print("✅ Selective mode works correctly")
    print()


def test_always_cancel_mode():
    """Test always cancel mode"""
    print("=" * 70)
    print("TEST 4: Always Cancel Mode")
    print("=" * 70)
    
    cleanup = ForcedPositionCleanup(
        dust_threshold_usd=1.00,
        max_positions=8,
        dry_run=True,
        cancel_open_orders=True,
        startup_only=False
    )
    
    assert cleanup.cancel_open_orders == True, "Should cancel open orders"
    assert cleanup.startup_only == False, "Should not be startup-only"
    assert cleanup.cancel_conditions is None, "Should have no conditions"
    
    # Test any position
    test_pos = {
        'symbol': 'ETH-USD',
        'size_usd': 10.00,
        'cleanup_type': CleanupType.DUST.value
    }
    
    should_cancel = cleanup._should_cancel_open_orders(test_pos, is_startup=False)
    assert should_cancel == True, "Should always cancel"
    
    print("✅ Always cancel mode works correctly")
    print()


def test_env_var_config():
    """Test environment variable configuration"""
    print("=" * 70)
    print("TEST 5: Environment Variable Configuration")
    print("=" * 70)
    
    # Set env vars
    os.environ['FORCED_CLEANUP_CANCEL_OPEN_ORDERS'] = 'true'
    os.environ['FORCED_CLEANUP_STARTUP_ONLY'] = 'true'
    
    cleanup = ForcedPositionCleanup(
        dust_threshold_usd=1.00,
        max_positions=8,
        dry_run=True
    )
    
    assert cleanup.cancel_open_orders == True, "Should read from env var"
    assert cleanup.startup_only == True, "Should read from env var"
    
    # Clean up env vars
    del os.environ['FORCED_CLEANUP_CANCEL_OPEN_ORDERS']
    del os.environ['FORCED_CLEANUP_STARTUP_ONLY']
    
    print("✅ Environment variable config works correctly")
    print()


def test_selective_env_config():
    """Test selective mode via environment variable"""
    print("=" * 70)
    print("TEST 6: Selective Mode via Environment Variable")
    print("=" * 70)
    
    # Set selective conditions
    os.environ['FORCED_CLEANUP_CANCEL_OPEN_ORDERS_IF'] = 'usd_value<2.0'
    
    cleanup = ForcedPositionCleanup(
        dust_threshold_usd=1.00,
        max_positions=8,
        dry_run=True
    )
    
    assert cleanup.cancel_open_orders == True, "Should enable from env var"
    assert cleanup.cancel_conditions is not None, "Should parse conditions"
    assert 'usd_value' in cleanup.cancel_conditions, "Should have usd_value condition"
    assert cleanup.cancel_conditions['usd_value'] == 2.0, "Should parse value correctly"
    
    # Clean up
    del os.environ['FORCED_CLEANUP_CANCEL_OPEN_ORDERS_IF']
    
    print("✅ Selective env config works correctly")
    print()


def test_malformed_conditions():
    """Test handling of malformed condition strings"""
    print("=" * 70)
    print("TEST 7: Malformed Condition Handling")
    print("=" * 70)
    
    # Test with malformed conditions - should handle gracefully
    cleanup = ForcedPositionCleanup(
        dust_threshold_usd=1.00,
        max_positions=8,
        dry_run=True,
        cancel_conditions="invalid_condition,usd_value<<1.0,rank>max_positions"
    )
    
    # Should still enable cancellation
    assert cleanup.cancel_open_orders == True, "Should enable even with some invalid conditions"
    
    # Should only parse valid condition
    assert 'rank_exceeds_cap' in cleanup.cancel_conditions, "Should parse valid condition"
    assert 'usd_value' not in cleanup.cancel_conditions, "Should skip malformed condition"
    
    print("✅ Malformed conditions handled gracefully")
    print()


if __name__ == "__main__":
    try:
        test_default_config()
        test_nuclear_mode()
        test_selective_mode()
        test_always_cancel_mode()
        test_env_var_config()
        test_selective_env_config()
        test_malformed_conditions()
        
        print("=" * 70)
        print("🎉 ALL TESTS PASSED")
        print("=" * 70)
        sys.exit(0)
    except AssertionError as e:
        print()
        print("=" * 70)
        print(f"❌ TEST FAILED: {e}")
        print("=" * 70)
        sys.exit(1)
    except Exception as e:
        print()
        print("=" * 70)
        print(f"❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        print("=" * 70)
        sys.exit(1)
