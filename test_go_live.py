#!/usr/bin/env python3
"""
Test script for go_live.py

Tests the core functionality of the go-live validator.
"""

import os
import sys
import tempfile
import shutil
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

def test_imports():
    """Test that all required modules can be imported"""
    print("Testing imports...")
    try:
        import go_live
        from go_live import GoLiveValidator, CheckResult
        print("✅ Imports successful")
        return True
    except ImportError as e:
        print(f"❌ Import failed: {e}")
        return False


def test_validator_initialization():
    """Test that validator can be initialized"""
    print("\nTesting validator initialization...")
    try:
        from go_live import GoLiveValidator
        validator = GoLiveValidator()
        assert validator.critical_failures == 0
        assert validator.warnings == 0
        assert len(validator.checks) == 0
        print("✅ Validator initialization successful")
        return True
    except Exception as e:
        print(f"❌ Initialization failed: {e}")
        return False


def test_dry_run_check():
    """Test DRY_RUN mode check"""
    print("\nTesting DRY_RUN mode check...")
    try:
        from go_live import GoLiveValidator
        
        # Test with DRY_RUN disabled (should pass)
        os.environ['DRY_RUN_MODE'] = 'false'
        validator = GoLiveValidator()
        validator._check_dry_run_mode()
        
        dry_run_check = [c for c in validator.checks if c.name == "DRY_RUN Mode Check"][0]
        assert dry_run_check.passed == True, "DRY_RUN=false should pass"
        print("✅ DRY_RUN check passed (disabled)")
        
        # Test with DRY_RUN enabled (should fail)
        os.environ['DRY_RUN_MODE'] = 'true'
        validator2 = GoLiveValidator()
        validator2._check_dry_run_mode()
        
        dry_run_check2 = [c for c in validator2.checks if c.name == "DRY_RUN Mode Check"][0]
        assert dry_run_check2.passed == False, "DRY_RUN=true should fail"
        print("✅ DRY_RUN check failed correctly (enabled)")
        
        # Restore
        os.environ['DRY_RUN_MODE'] = 'false'
        return True
    except Exception as e:
        print(f"❌ DRY_RUN check test failed: {e}")
        return False


def test_live_capital_check():
    """Test LIVE_CAPITAL_VERIFIED check"""
    print("\nTesting LIVE_CAPITAL_VERIFIED check...")
    try:
        from go_live import GoLiveValidator
        
        # Test with LIVE_CAPITAL_VERIFIED disabled (should fail)
        os.environ['LIVE_CAPITAL_VERIFIED'] = 'false'
        validator = GoLiveValidator()
        validator._check_live_capital_verified()
        
        check = [c for c in validator.checks if c.name == "Live Capital Verification"][0]
        assert check.passed == False, "LIVE_CAPITAL_VERIFIED=false should fail"
        print("✅ LIVE_CAPITAL_VERIFIED check failed correctly (disabled)")
        
        # Test with LIVE_CAPITAL_VERIFIED enabled (should pass)
        os.environ['LIVE_CAPITAL_VERIFIED'] = 'true'
        validator2 = GoLiveValidator()
        validator2._check_live_capital_verified()
        
        check2 = [c for c in validator2.checks if c.name == "Live Capital Verification"][0]
        assert check2.passed == True, "LIVE_CAPITAL_VERIFIED=true should pass"
        print("✅ LIVE_CAPITAL_VERIFIED check passed (enabled)")
        
        # Restore
        os.environ['LIVE_CAPITAL_VERIFIED'] = 'false'
        return True
    except Exception as e:
        print(f"❌ LIVE_CAPITAL_VERIFIED check test failed: {e}")
        return False


def test_emergency_stop_check():
    """Test emergency stop file check"""
    print("\nTesting emergency stop check...")
    try:
        from go_live import GoLiveValidator
        
        # Test without emergency stop (should pass)
        if os.path.exists('EMERGENCY_STOP'):
            os.remove('EMERGENCY_STOP')
        
        validator = GoLiveValidator()
        validator._check_emergency_stops()
        
        check = [c for c in validator.checks if c.name == "Emergency Stop Check"][0]
        assert check.passed == True, "No emergency stop file should pass"
        print("✅ Emergency stop check passed (no file)")
        
        # Test with emergency stop (should fail)
        with open('EMERGENCY_STOP', 'w') as f:
            f.write('STOP')
        
        validator2 = GoLiveValidator()
        validator2._check_emergency_stops()
        
        check2 = [c for c in validator2.checks if c.name == "Emergency Stop Check"][0]
        assert check2.passed == False, "Emergency stop file should fail"
        print("✅ Emergency stop check failed correctly (file present)")
        
        # Clean up
        os.remove('EMERGENCY_STOP')
        return True
    except Exception as e:
        print(f"❌ Emergency stop check test failed: {e}")
        if os.path.exists('EMERGENCY_STOP'):
            os.remove('EMERGENCY_STOP')
        return False


def test_capital_safety_check():
    """Test capital safety threshold check"""
    print("\nTesting capital safety check...")
    try:
        from go_live import GoLiveValidator
        
        validator = GoLiveValidator()
        validator._check_capital_safety()
        
        check = [c for c in validator.checks if c.name == "Capital Safety Thresholds"][0]
        # Should pass if capital_reservation_manager module is available
        print(f"✅ Capital safety check completed: {check.message}")
        return True
    except Exception as e:
        print(f"❌ Capital safety check test failed: {e}")
        return False


def test_multi_account_isolation_check():
    """Test multi-account isolation check"""
    print("\nTesting multi-account isolation check...")
    try:
        from go_live import GoLiveValidator
        
        validator = GoLiveValidator()
        validator._check_multi_account_isolation()
        
        check = [c for c in validator.checks if c.name == "Multi-Account Isolation"][0]
        # Should pass if account_isolation_manager module is available
        print(f"✅ Multi-account isolation check completed: {check.message}")
        return True
    except Exception as e:
        print(f"❌ Multi-account isolation check test failed: {e}")
        return False


def run_all_tests():
    """Run all tests"""
    print("=" * 80)
    print("🧪 RUNNING GO_LIVE.PY TESTS")
    print("=" * 80)
    
    tests = [
        ("Imports", test_imports),
        ("Validator Initialization", test_validator_initialization),
        ("DRY_RUN Check", test_dry_run_check),
        ("LIVE_CAPITAL_VERIFIED Check", test_live_capital_check),
        ("Emergency Stop Check", test_emergency_stop_check),
        ("Capital Safety Check", test_capital_safety_check),
        ("Multi-Account Isolation Check", test_multi_account_isolation_check),
    ]
    
    results = []
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"❌ Test '{test_name}' crashed: {e}")
            results.append((test_name, False))
    
    # Summary
    print("\n" + "=" * 80)
    print("📊 TEST SUMMARY")
    print("=" * 80)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status} - {test_name}")
    
    print("\n" + "=" * 80)
    print(f"Results: {passed}/{total} tests passed")
    print("=" * 80)
    
    return passed == total


if __name__ == '__main__':
    success = run_all_tests()
    sys.exit(0 if success else 1)
