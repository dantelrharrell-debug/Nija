"""
Test script for phantom position cleanup

Tests the new phantom position cleanup logic:
1. When balance is zero but position is tracked, position is cleared from tracker
2. Periodic sync removes orphaned positions
3. Position tracker properly syncs with broker positions

This test validates the phantom position cleanup without requiring live broker connection.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tempfile
import json
from position_tracker import PositionTracker


def test_phantom_position_cleanup():
    """Test that phantom positions (tracked but not on exchange) are cleared"""
    print("=" * 70)
    print("TEST 1: Phantom Position Cleanup via sync_with_broker")
    print("=" * 70)

    # Create a temporary file for position tracking
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        temp_file = f.name

    try:
        # Initialize tracker
        tracker = PositionTracker(storage_file=temp_file)

        # Track some positions
        tracker.track_entry('ONDO-USD', entry_price=0.35, quantity=15.92884793, size_usd=5.57)
        tracker.track_entry('RENDER-USD', entry_price=3.21, quantity=1.0, size_usd=3.21)
        tracker.track_entry('BTC-USD', entry_price=50000.0, quantity=0.001, size_usd=50.0)

        print(f"Tracked {len(tracker.get_all_positions())} positions")
        print(f"Positions: {tracker.get_all_positions()}")

        # Simulate broker positions (ONDO and RENDER don't exist, only BTC exists)
        broker_positions = [
            {'symbol': 'BTC-USD', 'quantity': 0.001, 'currency': 'BTC'}
        ]

        # Sync with broker - should remove ONDO and RENDER
        removed = tracker.sync_with_broker(broker_positions)

        print(f"\nRemoved {removed} phantom positions")
        print(f"Remaining positions: {tracker.get_all_positions()}")

        # Verify that phantom positions were removed
        assert removed == 2, f"Expected 2 positions removed, got {removed}"
        assert 'BTC-USD' in tracker.get_all_positions(), "BTC-USD should still be tracked"
        assert 'ONDO-USD' not in tracker.get_all_positions(), "ONDO-USD should be removed"
        assert 'RENDER-USD' not in tracker.get_all_positions(), "RENDER-USD should be removed"

        print("✅ PASSED: Phantom positions correctly removed")
        print()

    finally:
        # Clean up temp file
        if os.path.exists(temp_file):
            os.remove(temp_file)


def test_zero_balance_position_exit():
    """Test that track_exit properly removes positions"""
    print("=" * 70)
    print("TEST 2: Position Exit Tracking")
    print("=" * 70)

    # Create a temporary file for position tracking
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        temp_file = f.name

    try:
        # Initialize tracker
        tracker = PositionTracker(storage_file=temp_file)

        # Track a position
        tracker.track_entry('ONDO-USD', entry_price=0.35, quantity=15.92884793, size_usd=5.57)

        print(f"Tracked position: {tracker.get_position('ONDO-USD')}")

        # Simulate full exit (None quantity = full exit)
        success = tracker.track_exit('ONDO-USD', exit_quantity=None)

        print(f"Exit tracked: {success}")
        print(f"Position after exit: {tracker.get_position('ONDO-USD')}")

        # Verify position was removed
        assert success, "Exit should succeed"
        assert tracker.get_position('ONDO-USD') is None, "Position should be removed after full exit"

        print("✅ PASSED: Full exit properly removes position")
        print()

    finally:
        # Clean up temp file
        if os.path.exists(temp_file):
            os.remove(temp_file)


def test_partial_exit():
    """Test that partial exits reduce quantity correctly"""
    print("=" * 70)
    print("TEST 3: Partial Exit Tracking")
    print("=" * 70)

    # Create a temporary file for position tracking
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        temp_file = f.name

    try:
        # Initialize tracker
        tracker = PositionTracker(storage_file=temp_file)

        # Track a position
        tracker.track_entry('BTC-USD', entry_price=50000.0, quantity=0.1, size_usd=5000.0)

        initial = tracker.get_position('BTC-USD')
        print(f"Initial position: qty={initial['quantity']}, size=${initial['size_usd']:.2f}")

        # Simulate partial exit (sell 0.03 BTC)
        success = tracker.track_exit('BTC-USD', exit_quantity=0.03)

        updated = tracker.get_position('BTC-USD')
        print(f"After partial exit: qty={updated['quantity']}, size=${updated['size_usd']:.2f}")

        # Verify partial exit
        assert success, "Partial exit should succeed"
        assert updated is not None, "Position should still exist after partial exit"
        assert abs(updated['quantity'] - 0.07) < 0.0001, f"Expected quantity 0.07, got {updated['quantity']}"
        # Size should be proportional: 0.07/0.1 * 5000 = 3500
        assert abs(updated['size_usd'] - 3500.0) < 1.0, f"Expected size $3500, got ${updated['size_usd']:.2f}"

        print("✅ PASSED: Partial exit correctly reduces quantity and size")
        print()

    finally:
        # Clean up temp file
        if os.path.exists(temp_file):
            os.remove(temp_file)


def test_sync_with_empty_broker():
    """Test sync when broker has no positions (all phantom)"""
    print("=" * 70)
    print("TEST 4: Sync with Empty Broker (All Phantom)")
    print("=" * 70)

    # Create a temporary file for position tracking
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        temp_file = f.name

    try:
        # Initialize tracker
        tracker = PositionTracker(storage_file=temp_file)

        # Track some positions
        tracker.track_entry('ONDO-USD', entry_price=0.35, quantity=15.92884793, size_usd=5.57)
        tracker.track_entry('RENDER-USD', entry_price=3.21, quantity=1.0, size_usd=3.21)

        print(f"Tracked {len(tracker.get_all_positions())} positions")

        # Sync with empty broker (all positions are phantom)
        broker_positions = []
        removed = tracker.sync_with_broker(broker_positions)

        print(f"Removed {removed} phantom positions")
        print(f"Remaining positions: {tracker.get_all_positions()}")

        # Verify all positions were removed
        assert removed == 2, f"Expected 2 positions removed, got {removed}"
        assert len(tracker.get_all_positions()) == 0, "All positions should be removed"

        print("✅ PASSED: All phantom positions removed when broker is empty")
        print()

    finally:
        # Clean up temp file
        if os.path.exists(temp_file):
            os.remove(temp_file)


if __name__ == '__main__':
    print("\n" + "=" * 70)
    print("PHANTOM POSITION CLEANUP TESTS")
    print("=" * 70 + "\n")

    try:
        test_phantom_position_cleanup()
        test_zero_balance_position_exit()
        test_partial_exit()
        test_sync_with_empty_broker()

        print("=" * 70)
        print("✅ ALL TESTS PASSED")
        print("=" * 70)

    except AssertionError as e:
        print("\n" + "=" * 70)
        print(f"❌ TEST FAILED: {e}")
        print("=" * 70)
        sys.exit(1)
    except Exception as e:
        print("\n" + "=" * 70)
        print(f"❌ TEST ERROR: {e}")
        import traceback
        traceback.print_exc()
        print("=" * 70)
        sys.exit(1)
