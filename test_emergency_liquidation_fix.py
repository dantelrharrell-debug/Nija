#!/usr/bin/env python3
"""
Test: Verify Emergency Liquidation Module Fix

This test verifies the fix for the crash:
- ModuleNotFoundError: No module named 'emergency_liquidation'
- NameError: name 'logger' is not defined

The fix includes:
1. Creating the emergency_liquidation.py module
2. Implementing EmergencyLiquidator class
3. Moving logger initialization before import attempt
"""

import sys
import os

# Setup environment
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))


def test_emergency_liquidation_module_exists():
    """Test that emergency_liquidation module can be imported."""
    print("\n" + "=" * 70)
    print("TEST 1: Emergency Liquidation Module Import")
    print("=" * 70)
    
    try:
        from emergency_liquidation import EmergencyLiquidator
        print("✅ PASS: emergency_liquidation module imported successfully")
        return True
    except ModuleNotFoundError as e:
        print(f"❌ FAIL: ModuleNotFoundError - {e}")
        return False


def test_emergency_liquidator_class():
    """Test that EmergencyLiquidator class works correctly."""
    print("\n" + "=" * 70)
    print("TEST 2: EmergencyLiquidator Functionality")
    print("=" * 70)
    
    try:
        from emergency_liquidation import EmergencyLiquidator
        
        liquidator = EmergencyLiquidator()
        
        # Test case 1: -0.5% loss (should NOT liquidate)
        position = {
            'symbol': 'BTC-USD',
            'entry_price': 100.0,
            'size_usd': 100.0,
            'side': 'long'
        }
        result = liquidator.should_force_liquidate(position, 99.5)
        assert result == False, "Should not liquidate at -0.5%"
        print("✅ Test 1a: -0.5% loss correctly does NOT trigger liquidation")
        
        # Test case 2: -1.5% loss (SHOULD liquidate)
        result = liquidator.should_force_liquidate(position, 98.5)
        assert result == True, "Should liquidate at -1.5%"
        print("✅ Test 1b: -1.5% loss correctly TRIGGERS liquidation")
        
        # Test case 3: Exactly -1.0% loss (SHOULD liquidate - at threshold)
        result = liquidator.should_force_liquidate(position, 99.0)
        assert result == True, "Should liquidate at -1.0%"
        print("✅ Test 1c: -1.0% loss correctly TRIGGERS liquidation")
        
        print("✅ PASS: EmergencyLiquidator works correctly")
        return True
        
    except Exception as e:
        print(f"❌ FAIL: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_nija_apex_strategy_import():
    """Test that nija_apex_strategy_v71 imports without errors."""
    print("\n" + "=" * 70)
    print("TEST 3: NIJA Apex Strategy V71 Import (With Mocks)")
    print("=" * 70)
    
    try:
        from unittest.mock import MagicMock
        
        # Mock dependencies
        sys.modules['pandas'] = MagicMock()
        sys.modules['numpy'] = MagicMock()
        sys.modules['indicators'] = MagicMock()
        sys.modules['risk_manager'] = MagicMock()
        sys.modules['execution_engine'] = MagicMock()
        
        # This import was failing before the fix
        from nija_apex_strategy_v71 import NIJAApexStrategyV71
        import nija_apex_strategy_v71
        
        # Verify the flag is set correctly
        assert hasattr(nija_apex_strategy_v71, 'EMERGENCY_LIQUIDATION_AVAILABLE')
        assert nija_apex_strategy_v71.EMERGENCY_LIQUIDATION_AVAILABLE == True
        
        print("✅ PASS: nija_apex_strategy_v71 imports without errors")
        print(f"✅ EMERGENCY_LIQUIDATION_AVAILABLE = True")
        return True
        
    except ModuleNotFoundError as e:
        print(f"❌ FAIL: ModuleNotFoundError - {e}")
        return False
    except NameError as e:
        print(f"❌ FAIL: NameError - {e}")
        return False
    except Exception as e:
        print(f"❌ FAIL: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_logger_initialization_order():
    """Test that logger is available during import."""
    print("\n" + "=" * 70)
    print("TEST 4: Logger Initialization Order")
    print("=" * 70)
    
    try:
        import logging
        
        # Read the source file to verify logger is defined before use
        source_file = os.path.join(os.path.dirname(__file__), 'bot', 'nija_apex_strategy_v71.py')
        with open(source_file, 'r') as f:
            lines = f.readlines()
        
        # Find line numbers
        logger_definition_line = None
        logger_usage_line = None
        
        for i, line in enumerate(lines, 1):
            if 'logger = logging.getLogger' in line and not line.strip().startswith('#'):
                logger_definition_line = i
            if 'logger.warning("Emergency liquidation module not available")' in line:
                logger_usage_line = i
        
        assert logger_definition_line is not None, "Logger definition not found"
        assert logger_usage_line is not None, "Logger usage not found"
        assert logger_definition_line < logger_usage_line, \
            f"Logger used at line {logger_usage_line} before definition at line {logger_definition_line}"
        
        print(f"✅ Logger defined at line {logger_definition_line}")
        print(f"✅ Logger first used at line {logger_usage_line}")
        print(f"✅ PASS: Logger is defined before use (prevents NameError)")
        return True
        
    except Exception as e:
        print(f"❌ FAIL: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    print("\n" + "=" * 70)
    print("EMERGENCY LIQUIDATION FIX VERIFICATION TEST SUITE")
    print("=" * 70)
    print("Testing fix for crash:")
    print("  - ModuleNotFoundError: No module named 'emergency_liquidation'")
    print("  - NameError: name 'logger' is not defined")
    print("=" * 70)
    
    results = []
    results.append(("Emergency Liquidation Module Import", test_emergency_liquidation_module_exists()))
    results.append(("EmergencyLiquidator Functionality", test_emergency_liquidator_class()))
    results.append(("NIJA Apex Strategy V71 Import", test_nija_apex_strategy_import()))
    results.append(("Logger Initialization Order", test_logger_initialization_order()))
    
    print("\n" + "=" * 70)
    print("TEST RESULTS SUMMARY")
    print("=" * 70)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {test_name}")
    
    print("=" * 70)
    print(f"TOTAL: {passed}/{total} tests passed")
    print("=" * 70)
    
    if passed == total:
        print("\n🎉 ALL TESTS PASSED - Bot crash is FIXED!")
        print("=" * 70)
        sys.exit(0)
    else:
        print(f"\n⚠️ {total - passed} test(s) failed")
        print("=" * 70)
        sys.exit(1)
