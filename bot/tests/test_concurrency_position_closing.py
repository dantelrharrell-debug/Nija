"""
Test script for concurrency fixes in position closing

Tests the 5 critical concurrency fixes implemented in Issue #1:
1. Fix #1: Atomic Position Close Lock - Prevents double-sells
2. Fix #2: Immediate Position State Flush - Deletes position after confirmed sell
3. Fix #3: Block Concurrent Exit - Prevents concurrent exit attempts
4. Fix #4: Mandatory Balance Refresh - Forces balance sync before emergency sells
5. Fix #5: Proper Orphan Resolution - Sync-rebuild-validate-sell flow

This test validates the concurrency protection mechanisms without full broker initialization.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import threading
import time
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime


def test_atomic_close_lock():
    """
    FIX #1: Test that closing_positions prevents double-sells
    
    Scenario: Two threads attempt to close the same position simultaneously
    Expected: Only one thread succeeds, second thread is blocked
    """
    print("=" * 70)
    print("TEST 1: Atomic Position Close Lock (FIX #1)")
    print("=" * 70)
    
    # Import execution engine
    from execution_engine import ExecutionEngine
    
    # Create mock broker
    mock_broker = Mock()
    mock_broker.place_market_order = Mock(return_value={
        'status': 'filled',
        'order_id': 'test-123'
    })
    
    # Create execution engine
    engine = ExecutionEngine(broker_client=mock_broker)
    
    # Add a test position
    engine.positions['BTC-USD'] = {
        'symbol': 'BTC-USD',
        'side': 'long',
        'entry_price': 50000.0,
        'position_size': 100.0,
        'quantity': 0.002,
        'remaining_size': 1.0,
        'position_id': 'pos-123'
    }
    
    # Track how many times the sell was attempted
    sell_attempts = []
    
    def attempt_close():
        """Attempt to close position"""
        result = engine.execute_exit('BTC-USD', 50500.0, 1.0, "Test close")
        sell_attempts.append(result)
    
    # Launch two threads simultaneously trying to close the same position
    thread1 = threading.Thread(target=attempt_close)
    thread2 = threading.Thread(target=attempt_close)
    
    thread1.start()
    thread2.start()
    
    thread1.join()
    thread2.join()
    
    # Verify results
    print(f"Sell attempts: {sell_attempts}")
    print(f"Broker place_market_order called {mock_broker.place_market_order.call_count} times")
    
    # One should succeed, one should be blocked
    assert sell_attempts.count(True) == 1, f"Expected exactly 1 successful sell, got {sell_attempts.count(True)}"
    assert sell_attempts.count(False) == 1, f"Expected exactly 1 blocked sell, got {sell_attempts.count(False)}"
    
    # Broker should only be called once (double-sell prevented)
    assert mock_broker.place_market_order.call_count == 1, \
        f"Expected broker to be called once, got {mock_broker.place_market_order.call_count} calls"
    
    # Position should be removed from tracking (Fix #2)
    assert 'BTC-USD' not in engine.positions, "Position should be deleted after close"
    
    # Locks should be released
    assert 'BTC-USD' not in engine.closing_positions, "Symbol should be removed from closing_positions"
    assert 'BTC-USD' not in engine.active_exit_orders, "Symbol should be removed from active_exit_orders"
    
    print("✅ PASSED: Atomic close lock prevents double-sells")
    print("✅ PASSED: Position state flushed immediately after close")
    print("✅ PASSED: Locks properly released after completion")
    print()


def test_concurrent_exit_blocking():
    """
    FIX #3: Test that active_exit_orders blocks concurrent exit attempts
    
    Scenario: Exit order in progress, another thread attempts concurrent exit
    Expected: Second exit is blocked while first is active
    """
    print("=" * 70)
    print("TEST 2: Block Concurrent Exit (FIX #3)")
    print("=" * 70)
    
    from execution_engine import ExecutionEngine
    
    # Create mock broker with delayed response
    mock_broker = Mock()
    
    def delayed_order(*args, **kwargs):
        """Simulate slow broker response"""
        time.sleep(0.5)  # Simulate network delay
        return {
            'status': 'filled',
            'order_id': 'test-456'
        }
    
    mock_broker.place_market_order = Mock(side_effect=delayed_order)
    
    # Create execution engine
    engine = ExecutionEngine(broker_client=mock_broker)
    
    # Add a test position
    engine.positions['ETH-USD'] = {
        'symbol': 'ETH-USD',
        'side': 'long',
        'entry_price': 3000.0,
        'position_size': 100.0,
        'quantity': 0.033,
        'remaining_size': 1.0,
        'position_id': 'pos-456'
    }
    
    results = []
    
    def attempt_exit():
        """Attempt to exit position"""
        result = engine.execute_exit('ETH-USD', 3050.0, 1.0, "Concurrent test")
        results.append(result)
    
    # Launch two threads with slight delay
    thread1 = threading.Thread(target=attempt_exit)
    thread2 = threading.Thread(target=attempt_exit)
    
    thread1.start()
    time.sleep(0.1)  # Start second thread slightly after first
    thread2.start()
    
    thread1.join()
    thread2.join()
    
    print(f"Exit results: {results}")
    print(f"Broker called {mock_broker.place_market_order.call_count} times")
    
    # Only one exit should succeed
    assert results.count(True) == 1, f"Expected 1 success, got {results.count(True)}"
    assert results.count(False) == 1, f"Expected 1 blocked, got {results.count(False)}"
    
    # Broker should only be called once
    assert mock_broker.place_market_order.call_count == 1, \
        f"Expected 1 broker call, got {mock_broker.place_market_order.call_count}"
    
    print("✅ PASSED: Concurrent exit blocked during active exit")
    print()


def test_immediate_position_flush():
    """
    FIX #2: Test that position is immediately deleted after confirmed sell
    
    Scenario: Position closes successfully
    Expected: Position removed from internal dict immediately, not waiting for exchange refresh
    """
    print("=" * 70)
    print("TEST 3: Immediate Position State Flush (FIX #2)")
    print("=" * 70)
    
    from execution_engine import ExecutionEngine
    
    # Create mock broker
    mock_broker = Mock()
    mock_broker.place_market_order = Mock(return_value={
        'status': 'filled',
        'order_id': 'test-789'
    })
    
    # Create execution engine
    engine = ExecutionEngine(broker_client=mock_broker)
    
    # Add a test position
    symbol = 'SOL-USD'
    engine.positions[symbol] = {
        'symbol': symbol,
        'side': 'long',
        'entry_price': 100.0,
        'position_size': 50.0,
        'quantity': 0.5,
        'remaining_size': 1.0,
        'position_id': 'pos-789'
    }
    
    # Verify position exists
    assert symbol in engine.positions, "Position should exist before close"
    
    # Execute exit
    result = engine.execute_exit(symbol, 105.0, 1.0, "Test immediate flush")
    
    # Verify position was immediately deleted
    assert result is True, "Exit should succeed"
    assert symbol not in engine.positions, \
        "FIX #2: Position should be IMMEDIATELY deleted from internal state"
    
    # Verify locks are released
    assert symbol not in engine.closing_positions, "closing_positions should be cleared"
    assert symbol not in engine.active_exit_orders, "active_exit_orders should be cleared"
    
    print("✅ PASSED: Position immediately flushed from internal state after sell")
    print()


def test_balance_refresh_before_emergency_sell():
    """
    FIX #4: Test mandatory balance refresh before emergency sell
    
    Scenario: Emergency sell triggered
    Expected: Balance is refreshed before selling, validates available quantity
    """
    print("=" * 70)
    print("TEST 4: Mandatory Balance Refresh Before Emergency Sell (FIX #4)")
    print("=" * 70)
    
    from forced_stop_loss import ForcedStopLoss
    
    # Create mock broker
    mock_broker = Mock()
    mock_broker.place_market_order = Mock(return_value={
        'status': 'filled',
        'order_id': 'emergency-123'
    })
    
    # Mock balance refresh methods
    mock_broker.get_account_balance = Mock(return_value=150.0)
    mock_broker.get_positions = Mock(return_value=[
        {'symbol': 'BTC-USD', 'quantity': 0.002}
    ])
    mock_broker.get_current_price = Mock(return_value=50000.0)
    
    # Create forced stop loss system
    forced_sl = ForcedStopLoss(broker=mock_broker)
    
    # Execute emergency sell
    success, result, error = forced_sl.force_sell_position(
        symbol='BTC-USD',
        quantity=0.002,
        reason="Emergency stop loss"
    )
    
    # Verify balance refresh was called
    assert mock_broker.get_account_balance.called, \
        "FIX #4: get_account_balance should be called before emergency sell"
    assert mock_broker.get_positions.called, \
        "FIX #4: get_positions should be called to validate available quantity"
    
    # Verify sell succeeded
    assert success is True, "Emergency sell should succeed"
    assert mock_broker.place_market_order.called, "Broker should execute sell"
    
    print("✅ PASSED: Balance refreshed before emergency sell")
    print()


def test_orphan_position_resolution():
    """
    FIX #5: Test proper orphan resolution logic
    
    Scenario: Orphan position detected with mismatched size
    Expected: Sync balances → rebuild position → validate size → adjust to actual balance
    """
    print("=" * 70)
    print("TEST 5: Proper Orphan Resolution Logic (FIX #5)")
    print("=" * 70)
    
    from forced_stop_loss import ForcedStopLoss
    
    # Create mock broker
    mock_broker = Mock()
    mock_broker.place_market_order = Mock(return_value={
        'status': 'filled',
        'order_id': 'orphan-123'
    })
    
    # Mock orphan scenario: internal state says 0.005, broker has 0.003
    mock_broker.get_account_balance = Mock(return_value=100.0)
    mock_broker.get_positions = Mock(return_value=[
        {'symbol': 'ETH-USD', 'quantity': 0.003}  # Actual broker balance
    ])
    mock_broker.get_current_price = Mock(return_value=3000.0)
    
    # Create forced stop loss system
    forced_sl = ForcedStopLoss(broker=mock_broker)
    
    # Attempt to sell 0.005 (stale internal state)
    # Should detect mismatch and adjust to actual 0.003
    success, result, error = forced_sl.force_sell_position(
        symbol='ETH-USD',
        quantity=0.005,  # Stale quantity from internal state
        reason="Orphan position cleanup"
    )
    
    # Verify orphan resolution steps
    assert mock_broker.get_positions.called, \
        "FIX #5: Should sync balances to detect orphan"
    
    # Verify sell used actual balance (0.003), not stale state (0.005)
    assert success is True, "Orphan resolution should succeed"
    
    # Check that broker was called with adjusted quantity
    call_args = mock_broker.place_market_order.call_args
    actual_quantity = call_args[1]['quantity'] if call_args else None
    
    # Quantity should be adjusted to actual balance
    assert actual_quantity is not None, "Quantity should be passed to broker"
    assert actual_quantity <= 0.003, \
        f"FIX #5: Quantity should be adjusted to actual balance (≤0.003), got {actual_quantity}"
    
    print("✅ PASSED: Orphan position resolved with balance sync and adjustment")
    print()


def test_orphan_already_closed():
    """
    FIX #5: Test orphan resolution when position is already closed
    
    Scenario: Attempt to sell orphan position that no longer exists on broker
    Expected: Detect zero balance and abort (don't attempt sell)
    """
    print("=" * 70)
    print("TEST 6: Orphan Resolution - Already Closed (FIX #5)")
    print("=" * 70)
    
    from forced_stop_loss import ForcedStopLoss
    
    # Create mock broker
    mock_broker = Mock()
    
    # Position already closed on broker (empty positions list)
    mock_broker.get_account_balance = Mock(return_value=100.0)
    mock_broker.get_positions = Mock(return_value=[])  # No positions
    mock_broker.get_current_price = Mock(return_value=3000.0)
    
    # Create forced stop loss system
    forced_sl = ForcedStopLoss(broker=mock_broker)
    
    # Attempt to sell non-existent position
    success, result, error = forced_sl.force_sell_position(
        symbol='ETH-USD',
        quantity=0.005,
        reason="Stale orphan position"
    )
    
    # Verify sell was aborted (position already closed)
    assert success is False, "Should fail when position doesn't exist"
    assert "No" in error and "balance" in error, \
        f"Error should mention no balance available, got: {error}"
    
    # Verify broker sell was NOT called
    assert not mock_broker.place_market_order.called, \
        "FIX #5: Should NOT attempt sell when position already closed"
    
    print("✅ PASSED: Orphan resolution aborts when position already closed")
    print()


def test_partial_exit_lock_release():
    """
    Test that locks are properly released after partial exit
    
    Scenario: Partial position close (e.g., 50%)
    Expected: Locks released after partial close, allowing future exits
    """
    print("=" * 70)
    print("TEST 7: Lock Release After Partial Exit")
    print("=" * 70)
    
    from execution_engine import ExecutionEngine
    
    # Create mock broker
    mock_broker = Mock()
    mock_broker.place_market_order = Mock(return_value={
        'status': 'filled',
        'order_id': 'partial-123'
    })
    
    # Create execution engine
    engine = ExecutionEngine(broker_client=mock_broker)
    
    # Add a test position
    symbol = 'AVAX-USD'
    engine.positions[symbol] = {
        'symbol': symbol,
        'side': 'long',
        'entry_price': 40.0,
        'position_size': 100.0,
        'quantity': 2.5,
        'remaining_size': 1.0,
        'position_id': 'pos-partial'
    }
    
    # Execute 50% exit
    result = engine.execute_exit(symbol, 42.0, 0.5, "Partial profit take")
    
    # Verify partial exit succeeded
    assert result is True, "Partial exit should succeed"
    
    # Position should still exist (not fully closed)
    assert symbol in engine.positions, "Position should remain after partial close"
    assert engine.positions[symbol]['remaining_size'] == 0.5, \
        f"Remaining size should be 50%, got {engine.positions[symbol]['remaining_size']}"
    
    # Locks should be released (allowing future exits)
    assert symbol not in engine.closing_positions, \
        "closing_positions should be cleared after partial exit"
    assert symbol not in engine.active_exit_orders, \
        "active_exit_orders should be cleared after partial exit"
    
    # Should be able to exit remaining 50%
    result2 = engine.execute_exit(symbol, 43.0, 1.0, "Final exit")
    assert result2 is True, "Second exit should succeed (locks were released)"
    
    # Now position should be fully closed
    assert symbol not in engine.positions, "Position should be deleted after full close"
    
    print("✅ PASSED: Locks properly released after partial exit")
    print("✅ PASSED: Subsequent exit allowed after lock release")
    print()


def run_all_tests():
    """Run all concurrency tests"""
    print("\n")
    print("=" * 70)
    print("CONCURRENCY POSITION CLOSING TESTS - ISSUE #1 FIXES")
    print("=" * 70)
    print()
    
    try:
        test_atomic_close_lock()
        test_concurrent_exit_blocking()
        test_immediate_position_flush()
        test_balance_refresh_before_emergency_sell()
        test_orphan_position_resolution()
        test_orphan_already_closed()
        test_partial_exit_lock_release()
        
        print("=" * 70)
        print("✅ ALL CONCURRENCY TESTS PASSED")
        print("=" * 70)
        print()
        print("Summary:")
        print("  ✅ Fix #1: Atomic position close lock prevents double-sells")
        print("  ✅ Fix #2: Immediate position state flush after confirmed sell")
        print("  ✅ Fix #3: Concurrent exit blocked when active exit in progress")
        print("  ✅ Fix #4: Mandatory balance refresh before emergency sell")
        print("  ✅ Fix #5: Proper orphan resolution (sync-rebuild-validate-sell)")
        print()
        print("All 5 critical concurrency fixes are working correctly!")
        print()
        
        return True
        
    except AssertionError as e:
        print(f"❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False
    except Exception as e:
        print(f"❌ TEST ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    success = run_all_tests()
    sys.exit(0 if success else 1)
