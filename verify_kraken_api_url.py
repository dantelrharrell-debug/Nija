#!/usr/bin/env python3
"""
Kraken API Endpoint Verification Test

This test verifies that the NIJA bot is using the correct Kraken API endpoints
as specified in the Kraken REST API documentation.

Expected configuration:
- Base URI: https://api.kraken.com
- API Version: 0
- Private endpoints: https://api.kraken.com/0/private/{method}
- Public endpoints: https://api.kraken.com/0/public/{method}
"""

import sys
import os

# Expected Kraken API configuration constants
EXPECTED_KRAKEN_URI = "https://api.kraken.com"
EXPECTED_KRAKEN_VERSION = "0"

# Forbidden patterns that indicate manual URL override (instead of using library defaults)
# Format: (pattern, description)
FORBIDDEN_URL_PATTERNS = [
    ("self.api.uri =", "manual URI assignment after API initialization"),
    ("self.api.apiversion =", "manual API version override"),
]

# Add bot directory to path for imports when run from repository root
# This allows running: python3 verify_kraken_api_url.py
script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir not in sys.path:
    sys.path.insert(0, script_dir)


def verify_krakenex_library():
    """Verify the krakenex library is using correct default settings."""
    print("\n" + "=" * 70)
    print("TEST 1: Verify krakenex Library Default Configuration")
    print("=" * 70)
    
    try:
        import krakenex
        
        # Initialize API without credentials (testing defaults only)
        api = krakenex.API()
        
        # Verify base URI
        print(f"\nBase URI:")
        print(f"  Expected: {EXPECTED_KRAKEN_URI}")
        print(f"  Actual:   {api.uri}")
        
        if api.uri != EXPECTED_KRAKEN_URI:
            print(f"  ❌ FAIL: Base URI mismatch")
            return False
        print(f"  ✅ PASS")
        
        # Verify API version
        print(f"\nAPI Version:")
        print(f"  Expected: {EXPECTED_KRAKEN_VERSION}")
        print(f"  Actual:   {api.apiversion}")
        
        if api.apiversion != EXPECTED_KRAKEN_VERSION:
            print(f"  ❌ FAIL: API version mismatch")
            return False
        print(f"  ✅ PASS")
        
        # Test URL construction for private endpoints
        print(f"\nPrivate Endpoint URL Construction:")
        test_methods = ["Balance", "OpenOrders", "AddOrder", "CancelOrder"]
        
        for method in test_methods:
            expected_path = f"/{EXPECTED_KRAKEN_VERSION}/private/{method}"
            expected_full_url = f"{EXPECTED_KRAKEN_URI}/{EXPECTED_KRAKEN_VERSION}/private/{method}"
            
            # The library constructs the path as: /{apiversion}/private/{method}
            constructed_path = f"/{api.apiversion}/private/{method}"
            constructed_full_url = f"{api.uri}{constructed_path}"
            
            print(f"\n  Method: {method}")
            print(f"    Expected: {expected_full_url}")
            print(f"    Actual:   {constructed_full_url}")
            
            if constructed_full_url != expected_full_url:
                print(f"    ❌ FAIL: URL mismatch")
                return False
            print(f"    ✅ PASS")
        
        print(f"\n{'=' * 70}")
        print("✅ TEST 1 PASSED: krakenex library using correct configuration")
        print("=" * 70)
        return True
        
    except ImportError as e:
        print(f"❌ FAIL: Could not import krakenex library: {e}")
        return False
    except Exception as e:
        print(f"❌ FAIL: Unexpected error: {e}")
        return False


def verify_nija_broker_integration():
    """Verify NIJA's broker integration uses krakenex correctly."""
    print("\n" + "=" * 70)
    print("TEST 2: Verify NIJA Broker Integration")
    print("=" * 70)
    
    try:
        # Import NIJA's Kraken broker implementation
        from bot.broker_integration import KrakenBrokerAdapter
        
        print("\n✅ KrakenBrokerAdapter imported successfully")
        
        # Check that the class doesn't override the API URL
        import inspect
        source = inspect.getsource(KrakenBrokerAdapter)
        
        print("\nChecking for URL overrides (should be none):")
        for pattern, description in FORBIDDEN_URL_PATTERNS:
            if pattern in source:
                print(f"  ❌ FAIL: Found forbidden pattern: {pattern}")
                print(f"     Issue: {description}")
                return False
            print(f"  ✅ PASS: No '{pattern}' override found")
        
        # Verify it uses krakenex.API() correctly
        if "krakenex.API(" not in source:
            print(f"\n❌ FAIL: KrakenBrokerAdapter does not use krakenex.API()")
            return False
        print(f"\n✅ PASS: Uses krakenex.API() for initialization")
        
        print(f"\n{'=' * 70}")
        print("✅ TEST 2 PASSED: NIJA integration using krakenex correctly")
        print("=" * 70)
        return True
        
    except ImportError as e:
        print(f"❌ FAIL: Could not import NIJA broker integration: {e}")
        return False
    except Exception as e:
        print(f"❌ FAIL: Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return False


def verify_nija_broker_manager():
    """Verify NIJA's broker manager uses krakenex correctly."""
    print("\n" + "=" * 70)
    print("TEST 3: Verify NIJA Broker Manager")
    print("=" * 70)
    
    try:
        # Import NIJA's Kraken broker manager implementation
        from bot.broker_manager import KrakenBroker
        
        print("\n✅ KrakenBroker imported successfully")
        
        # Check that the class doesn't override the API URL
        import inspect
        source = inspect.getsource(KrakenBroker)
        
        print("\nChecking for URL overrides (should be none):")
        for pattern, description in FORBIDDEN_URL_PATTERNS:
            if pattern in source:
                print(f"  ❌ FAIL: Found forbidden pattern: {pattern}")
                print(f"     Issue: {description}")
                return False
            print(f"  ✅ PASS: No '{pattern}' override found")
        
        # Verify it uses krakenex.API() correctly
        if "krakenex.API(" not in source:
            print(f"\n❌ FAIL: KrakenBroker does not use krakenex.API()")
            return False
        print(f"\n✅ PASS: Uses krakenex.API() for initialization")
        
        print(f"\n{'=' * 70}")
        print("✅ TEST 3 PASSED: NIJA broker manager using krakenex correctly")
        print("=" * 70)
        return True
        
    except ImportError as e:
        print(f"❌ FAIL: Could not import NIJA broker manager: {e}")
        return False
    except Exception as e:
        print(f"❌ FAIL: Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all verification tests."""
    print("\n" + "=" * 70)
    print("KRAKEN API ENDPOINT VERIFICATION TEST SUITE")
    print("=" * 70)
    print("\nThis test suite verifies that NIJA is using the correct Kraken API")
    print("endpoints as specified in the official Kraken REST API documentation.")
    print(f"\nExpected configuration:")
    print(f"  - Base URI: {EXPECTED_KRAKEN_URI}")
    print(f"  - API Version: {EXPECTED_KRAKEN_VERSION}")
    print(f"  - Private endpoints: {EXPECTED_KRAKEN_URI}/{EXPECTED_KRAKEN_VERSION}/private/{{method}}")
    print(f"  - Public endpoints: {EXPECTED_KRAKEN_URI}/{EXPECTED_KRAKEN_VERSION}/public/{{method}}")
    
    # Run all tests
    results = []
    
    # Test 1: Verify krakenex library defaults
    results.append(("krakenex Library Configuration", verify_krakenex_library()))
    
    # Test 2: Verify NIJA broker integration
    results.append(("NIJA Broker Integration", verify_nija_broker_integration()))
    
    # Test 3: Verify NIJA broker manager
    results.append(("NIJA Broker Manager", verify_nija_broker_manager()))
    
    # Print summary
    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)
    
    all_passed = True
    for test_name, passed in results:
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"{status}: {test_name}")
        if not passed:
            all_passed = False
    
    print("=" * 70)
    
    if all_passed:
        print("\n🎉 ALL TESTS PASSED")
        print("\n✅ CONCLUSION: NIJA is using the correct Kraken API endpoints")
        print(f"   - Base: {EXPECTED_KRAKEN_URI.replace('https://', '')}")
        print(f"   - Private endpoints: {EXPECTED_KRAKEN_URI.replace('https://', '')}/{EXPECTED_KRAKEN_VERSION}/private/{{method}}")
        print("   - No changes required")
        print("\n" + "=" * 70)
        return 0
    else:
        print("\n❌ SOME TESTS FAILED")
        print("\n⚠️  WARNING: Incorrect Kraken API endpoint configuration detected")
        print("   Please review the failed tests and fix the implementation")
        print("\n" + "=" * 70)
        return 1


if __name__ == "__main__":
    sys.exit(main())
