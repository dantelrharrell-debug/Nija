#!/usr/bin/env python3
"""
Test script for NIJA Position Management State Machine.

This script validates:
1. State transitions work correctly
2. Invariants are enforced
3. Drain mode activates/deactivates properly
"""

import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bot.trading_strategy import PositionManagementState, StateInvariantValidator

def test_state_enum():
    """Test that state enum is properly defined."""
    print("Testing PositionManagementState enum...")
    assert PositionManagementState.NORMAL.value == "normal"
    assert PositionManagementState.DRAIN.value == "drain"
    assert PositionManagementState.FORCED_UNWIND.value == "forced_unwind"
    print("✅ State enum test passed")

def test_invariant_validation():
    """Test invariant validation logic."""
    print("\nTesting StateInvariantValidator...")
    
    # Test 1: NORMAL mode with no excess (valid)
    try:
        StateInvariantValidator.validate_state_invariants(
            PositionManagementState.NORMAL, 
            num_positions=5, 
            excess_positions=-3,  # 5 - 8 = -3
            max_positions=8
        )
        print("✅ Test 1 passed: NORMAL mode with -3 excess (under cap)")
    except AssertionError as e:
        print(f"❌ Test 1 failed: {e}")
        return False
    
    # Test 2: DRAIN mode with excess > 0 (valid)
    try:
        StateInvariantValidator.validate_state_invariants(
            PositionManagementState.DRAIN, 
            num_positions=10, 
            excess_positions=2,
            max_positions=8
        )
        print("✅ Test 2 passed: DRAIN mode with excess=2")
    except AssertionError as e:
        print(f"❌ Test 2 failed: {e}")
        return False
    
    # Test 3: DRAIN mode with excess <= 0 (should fail)
    try:
        StateInvariantValidator.validate_state_invariants(
            PositionManagementState.DRAIN, 
            num_positions=8, 
            excess_positions=0,
            max_positions=8
        )
        print("❌ Test 3 failed: DRAIN mode should not allow excess=0")
        return False
    except AssertionError:
        print("✅ Test 3 passed: DRAIN mode correctly rejects excess=0")
    
    # Test 4: Position count non-negative invariant
    try:
        StateInvariantValidator.validate_state_invariants(
            PositionManagementState.NORMAL, 
            num_positions=-1, 
            excess_positions=-9,
            max_positions=8
        )
        print("❌ Test 4 failed: Should reject negative position count")
        return False
    except AssertionError:
        print("✅ Test 4 passed: Correctly rejects negative position count")
    
    # Test 5: NORMAL mode with negative excess (valid - under cap)
    try:
        StateInvariantValidator.validate_state_invariants(
            PositionManagementState.NORMAL, 
            num_positions=5, 
            excess_positions=-3,
            max_positions=8
        )
        print("✅ Test 5 passed: NORMAL mode accepts negative excess")
    except AssertionError as e:
        print(f"❌ Test 5 failed: {e}")
        return False
    
    print("✅ All invariant validation tests passed")
    return True

def test_state_transitions():
    """Test state transition validation."""
    print("\nTesting state transitions...")
    
    # Test 1: NORMAL → DRAIN (valid)
    result = StateInvariantValidator.validate_state_transition(
        PositionManagementState.NORMAL,
        PositionManagementState.DRAIN,
        num_positions=10,
        excess_positions=2
    )
    assert result == True, "NORMAL → DRAIN should be valid"
    print("✅ Test 1 passed: NORMAL → DRAIN")
    
    # Test 2: DRAIN → NORMAL (valid)
    result = StateInvariantValidator.validate_state_transition(
        PositionManagementState.DRAIN,
        PositionManagementState.NORMAL,
        num_positions=7,
        excess_positions=-1
    )
    assert result == True, "DRAIN → NORMAL should be valid"
    print("✅ Test 2 passed: DRAIN → NORMAL")
    
    # Test 3: NORMAL → FORCED_UNWIND (valid)
    result = StateInvariantValidator.validate_state_transition(
        PositionManagementState.NORMAL,
        PositionManagementState.FORCED_UNWIND,
        num_positions=5,
        excess_positions=-3
    )
    assert result == True, "NORMAL → FORCED_UNWIND should be valid"
    print("✅ Test 3 passed: NORMAL → FORCED_UNWIND")
    
    # Test 4: Self-transition (valid)
    result = StateInvariantValidator.validate_state_transition(
        PositionManagementState.NORMAL,
        PositionManagementState.NORMAL,
        num_positions=5,
        excess_positions=-3
    )
    assert result == True, "Self-transition should be valid"
    print("✅ Test 4 passed: Self-transition")
    
    print("✅ All state transition tests passed")
    return True

def test_drain_mode_condition():
    """Test that drain mode only activates when excess > 0."""
    print("\nTesting drain mode activation logic...")
    
    MAX_POSITIONS = 8
    
    # Test scenarios
    scenarios = [
        (5, -3, PositionManagementState.NORMAL, "Under cap"),
        (8, 0, PositionManagementState.NORMAL, "At cap"),
        (9, 1, PositionManagementState.DRAIN, "1 over cap"),
        (10, 2, PositionManagementState.DRAIN, "2 over cap"),
        (0, -8, PositionManagementState.NORMAL, "No positions"),
    ]
    
    for num_pos, expected_excess, expected_state, description in scenarios:
        actual_excess = num_pos - MAX_POSITIONS
        assert actual_excess == expected_excess, f"Excess calculation error: {description}"
        
        # Determine expected state based on excess
        if expected_excess > 0:
            state = PositionManagementState.DRAIN
        else:
            state = PositionManagementState.NORMAL
        
        assert state == expected_state, f"State mismatch: {description}"
        print(f"✅ {description}: positions={num_pos}, excess={actual_excess}, state={state.value}")
    
    print("✅ All drain mode activation tests passed")
    return True

def main():
    """Run all tests."""
    print("=" * 80)
    print("NIJA STATE MACHINE TEST SUITE")
    print("=" * 80)
    
    all_passed = True
    
    try:
        test_state_enum()
        all_passed &= test_invariant_validation()
        all_passed &= test_state_transitions()
        all_passed &= test_drain_mode_condition()
    except Exception as e:
        print(f"\n❌ Test suite failed with error: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    print("\n" + "=" * 80)
    if all_passed:
        print("✅ ALL TESTS PASSED")
        print("=" * 80)
        return 0
    else:
        print("❌ SOME TESTS FAILED")
        print("=" * 80)
        return 1

if __name__ == "__main__":
    sys.exit(main())
