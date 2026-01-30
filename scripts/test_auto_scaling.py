#!/usr/bin/env python3
"""
Test script for Auto-Scaling Configuration Module
Validates auto-scaling functionality and tier transitions
"""

import sys
import os
import tempfile
from pathlib import Path

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from bot.auto_scaling_config import (
    AutoScalingEngine,
    ScalingTier,
    SCALING_TIERS,
    auto_scale,
    get_current_tier_info,
    get_scaling_summary,
)


def test_tier_matching():
    """Test that tiers match correct equity ranges"""
    print("Testing tier matching...")
    
    test_cases = [
        (15.0, "STARTER"),
        (100.0, "STARTER"),
        (249.99, "STARTER"),
        (250.0, "GROWTH"),
        (400.0, "GROWTH"),
        (499.99, "GROWTH"),
        (500.0, "ADVANCED"),
        (750.0, "ADVANCED"),
        (999.99, "ADVANCED"),
        (1000.0, "ELITE"),
        (10000.0, "ELITE"),
    ]
    
    all_passed = True
    
    for equity, expected_tier_name in test_cases:
        tier = next((t for t in SCALING_TIERS if t.matches(equity)), None)
        
        if tier is None:
            print(f"  ❌ FAILED: No tier found for ${equity:.2f}")
            all_passed = False
        elif tier.name != expected_tier_name:
            print(f"  ❌ FAILED: ${equity:.2f} should be {expected_tier_name}, got {tier.name}")
            all_passed = False
    
    if all_passed:
        print(f"  ✅ PASSED: All {len(test_cases)} tier matches correct")
    
    return all_passed


def test_tier_transitions():
    """Test tier transitions as equity grows"""
    print("\nTesting tier transitions...")
    
    # Create engine with temp state file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        temp_state_file = f.name
    
    try:
        engine = AutoScalingEngine(state_file=temp_state_file)
        
        # Simulate equity growth
        transitions = [
            (50.0, "STARTER", True),    # Initial - always scales
            (100.0, "STARTER", False),  # Same tier
            (250.0, "GROWTH", True),    # Upgrade to GROWTH
            (350.0, "GROWTH", False),   # Same tier
            (500.0, "ADVANCED", True),  # Upgrade to ADVANCED
            (1000.0, "ELITE", True),    # Upgrade to ELITE
        ]
        
        all_passed = True
        
        for equity, expected_tier, should_scale in transitions:
            scaled, old_tier, new_tier = engine.check_and_scale(equity)
            
            if new_tier is None:
                print(f"  ❌ FAILED: No tier returned for ${equity:.2f}")
                all_passed = False
                continue
            
            if new_tier.name != expected_tier:
                print(f"  ❌ FAILED: ${equity:.2f} should be {expected_tier}, got {new_tier.name}")
                all_passed = False
                continue
            
            if scaled != should_scale:
                print(f"  ❌ FAILED: ${equity:.2f} scaling should be {should_scale}, got {scaled}")
                all_passed = False
                continue
        
        if all_passed:
            print(f"  ✅ PASSED: All tier transitions correct")
        
        return all_passed
        
    finally:
        # Clean up temp file
        if os.path.exists(temp_state_file):
            os.unlink(temp_state_file)


def test_tier_properties():
    """Test that tier properties are correct"""
    print("\nTesting tier properties...")
    
    expected_properties = {
        "STARTER": {
            'max_positions': 2,
            'risk_per_trade': 3.0,
            'copy_trading': False,
            'leverage_enabled': False,
        },
        "GROWTH": {
            'max_positions': 3,
            'risk_per_trade': 4.0,
            'copy_trading': False,
            'leverage_enabled': False,
        },
        "ADVANCED": {
            'max_positions': 4,
            'risk_per_trade': 4.0,
            'copy_trading': True,
            'leverage_enabled': False,
        },
        "ELITE": {
            'max_positions': 6,
            'risk_per_trade': 5.0,
            'copy_trading': True,
            'leverage_enabled': True,
        },
    }
    
    all_passed = True
    
    for tier in SCALING_TIERS:
        if tier.name not in expected_properties:
            print(f"  ❌ FAILED: Unexpected tier {tier.name}")
            all_passed = False
            continue
        
        expected = expected_properties[tier.name]
        
        checks = [
            (tier.max_positions == expected['max_positions'], 
             f"{tier.name}: max_positions should be {expected['max_positions']}, got {tier.max_positions}"),
            (tier.risk_per_trade == expected['risk_per_trade'], 
             f"{tier.name}: risk_per_trade should be {expected['risk_per_trade']}, got {tier.risk_per_trade}"),
            (tier.copy_trading == expected['copy_trading'], 
             f"{tier.name}: copy_trading should be {expected['copy_trading']}, got {tier.copy_trading}"),
            (tier.leverage_enabled == expected['leverage_enabled'], 
             f"{tier.name}: leverage_enabled should be {expected['leverage_enabled']}, got {tier.leverage_enabled}"),
        ]
        
        for check, msg in checks:
            if not check:
                print(f"  ❌ FAILED: {msg}")
                all_passed = False
    
    if all_passed:
        print(f"  ✅ PASSED: All tier properties correct")
    
    return all_passed


def test_auto_scale_function():
    """Test convenience auto_scale function"""
    print("\nTesting auto_scale convenience function...")
    
    # Create temp state file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        temp_state_file = f.name
    
    try:
        # Import fresh to reset global state
        import importlib
        import bot.auto_scaling_config as asc
        importlib.reload(asc)
        
        # Override global engine with temp state
        asc._auto_scaling_engine = AutoScalingEngine(state_file=temp_state_file)
        
        # Test auto_scale function
        scaled, old_tier, new_tier = asc.auto_scale(250.0)
        
        if new_tier != "GROWTH":
            print(f"  ❌ FAILED: auto_scale(250.0) should return GROWTH, got {new_tier}")
            return False
        
        # Test no scaling on same tier
        scaled, old_tier, new_tier = asc.auto_scale(300.0)
        
        if scaled:
            print(f"  ❌ FAILED: auto_scale(300.0) should not scale (same tier)")
            return False
        
        if new_tier != "GROWTH":
            print(f"  ❌ FAILED: auto_scale(300.0) should return GROWTH, got {new_tier}")
            return False
        
        print(f"  ✅ PASSED: auto_scale function works correctly")
        return True
        
    finally:
        if os.path.exists(temp_state_file):
            os.unlink(temp_state_file)


def test_state_persistence():
    """Test that state is persisted correctly"""
    print("\nTesting state persistence...")
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        temp_state_file = f.name
    
    try:
        # Create engine and scale
        engine1 = AutoScalingEngine(state_file=temp_state_file)
        engine1.check_and_scale(500.0)
        
        # Create new engine with same state file
        engine2 = AutoScalingEngine(state_file=temp_state_file)
        
        # Check that state was loaded
        current_tier = engine2.state_manager.get_current_tier()
        
        if current_tier != "ADVANCED":
            print(f"  ❌ FAILED: Persisted tier should be ADVANCED, got {current_tier}")
            return False
        
        print(f"  ✅ PASSED: State persistence works correctly")
        return True
        
    finally:
        if os.path.exists(temp_state_file):
            os.unlink(temp_state_file)


def test_upgrade_history():
    """Test upgrade history tracking"""
    print("\nTesting upgrade history...")
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        temp_state_file = f.name
    
    try:
        engine = AutoScalingEngine(state_file=temp_state_file)
        
        # Perform multiple upgrades
        engine.check_and_scale(100.0)
        engine.check_and_scale(250.0)
        engine.check_and_scale(500.0)
        engine.check_and_scale(1000.0)
        
        # Get history
        history = engine.state_manager.get_upgrade_history()
        
        if len(history) != 4:
            print(f"  ❌ FAILED: History should have 4 entries, got {len(history)}")
            return False
        
        # Check transitions
        expected_transitions = [
            (None, "STARTER"),
            ("STARTER", "GROWTH"),
            ("GROWTH", "ADVANCED"),
            ("ADVANCED", "ELITE"),
        ]
        
        for i, (expected_from, expected_to) in enumerate(expected_transitions):
            if history[i]['from_tier'] != expected_from or history[i]['to_tier'] != expected_to:
                print(f"  ❌ FAILED: Transition {i} should be {expected_from}→{expected_to}, got {history[i]['from_tier']}→{history[i]['to_tier']}")
                return False
        
        print(f"  ✅ PASSED: Upgrade history tracking works correctly")
        return True
        
    finally:
        if os.path.exists(temp_state_file):
            os.unlink(temp_state_file)


def test_progress_to_next_tier():
    """Test progress calculation to next tier"""
    print("\nTesting progress to next tier...")
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        temp_state_file = f.name
    
    try:
        engine = AutoScalingEngine(state_file=temp_state_file)
        
        # Set equity to $750 (ADVANCED tier, $250 from ELITE)
        engine.check_and_scale(750.0)
        
        progress = engine.get_progress_to_next_tier()
        
        if progress is None:
            print(f"  ❌ FAILED: Progress should not be None")
            return False
        
        if progress['next_tier']['name'] != 'ELITE':
            print(f"  ❌ FAILED: Next tier should be ELITE, got {progress['next_tier']['name']}")
            return False
        
        if abs(progress['equity_needed'] - 250.0) > 0.01:
            print(f"  ❌ FAILED: Equity needed should be 250.0, got {progress['equity_needed']}")
            return False
        
        if abs(progress['progress_pct'] - 75.0) > 0.1:
            print(f"  ❌ FAILED: Progress should be 75%, got {progress['progress_pct']}")
            return False
        
        print(f"  ✅ PASSED: Progress calculation works correctly")
        return True
        
    finally:
        if os.path.exists(temp_state_file):
            os.unlink(temp_state_file)


def run_all_tests():
    """Run all tests"""
    print("="*80)
    print("AUTO-SCALING CONFIGURATION MODULE - TEST SUITE")
    print("="*80)
    
    tests = [
        ("Tier Matching", test_tier_matching),
        ("Tier Transitions", test_tier_transitions),
        ("Tier Properties", test_tier_properties),
        ("Auto-Scale Function", test_auto_scale_function),
        ("State Persistence", test_state_persistence),
        ("Upgrade History", test_upgrade_history),
        ("Progress to Next Tier", test_progress_to_next_tier),
    ]
    
    results = []
    
    for test_name, test_func in tests:
        try:
            passed = test_func()
            results.append((test_name, passed))
        except Exception as e:
            print(f"\n  ❌ EXCEPTION in {test_name}: {e}")
            import traceback
            traceback.print_exc()
            results.append((test_name, False))
    
    # Print summary
    print("\n" + "="*80)
    print("TEST SUMMARY")
    print("="*80)
    
    total_tests = len(results)
    passed_tests = sum(1 for _, passed in results if passed)
    
    for test_name, passed in results:
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"{status}: {test_name}")
    
    print("\n" + "="*80)
    print(f"TOTAL: {passed_tests}/{total_tests} tests passed")
    
    if passed_tests == total_tests:
        print("🎉 ALL TESTS PASSED!")
        print("="*80)
        return 0
    else:
        print(f"⚠️  {total_tests - passed_tests} tests failed")
        print("="*80)
        return 1


if __name__ == "__main__":
    sys.exit(run_all_tests())
