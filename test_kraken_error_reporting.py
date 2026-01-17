#!/usr/bin/env python3
"""
Test script to verify Kraken connection error reporting.

This test ensures that when Kraken connection fails, the error message
is properly captured in last_connection_error.
"""

import os
import sys

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

def test_kraken_error_reporting():
    """Test that Kraken connection errors are properly reported."""
    print("=" * 70)
    print("Testing Kraken Connection Error Reporting")
    print("=" * 70)
    
    # Import after path setup
    from broker_manager import KrakenBroker, AccountType
    
    # Test Case 1: Missing credentials
    print("\n📋 Test Case 1: Missing Credentials")
    print("-" * 70)
    
    # Clear any existing credentials
    for key in ['KRAKEN_MASTER_API_KEY', 'KRAKEN_MASTER_API_SECRET', 
                'KRAKEN_API_KEY', 'KRAKEN_API_SECRET']:
        if key in os.environ:
            del os.environ[key]
    
    kraken = KrakenBroker(account_type=AccountType.MASTER)
    result = kraken.connect()
    
    print(f"Connection result: {result}")
    print(f"Credentials configured: {kraken.credentials_configured}")
    print(f"Last connection error: {kraken.last_connection_error}")
    
    if not result and not kraken.credentials_configured:
        print("✅ PASS: Credentials not configured, connection returned False")
        # When credentials are not configured, last_connection_error may be None
        # This is expected behavior
    else:
        print("❌ FAIL: Expected connection to fail with credentials_configured=False")
    
    # Test Case 2: Malformed credentials (whitespace only)
    print("\n📋 Test Case 2: Malformed Credentials (Whitespace Only)")
    print("-" * 70)
    
    os.environ['KRAKEN_MASTER_API_KEY'] = "   "  # Whitespace only
    os.environ['KRAKEN_MASTER_API_SECRET'] = "   "  # Whitespace only
    
    kraken2 = KrakenBroker(account_type=AccountType.MASTER)
    result2 = kraken2.connect()
    
    print(f"Connection result: {result2}")
    print(f"Credentials configured: {kraken2.credentials_configured}")
    print(f"Last connection error: {kraken2.last_connection_error}")
    
    if not result2 and kraken2.last_connection_error:
        if "whitespace" in kraken2.last_connection_error.lower():
            print("✅ PASS: Whitespace credentials detected, error message set")
        else:
            print(f"⚠️  WARNING: Error message set but doesn't mention whitespace: {kraken2.last_connection_error}")
    else:
        print("❌ FAIL: Expected connection to fail with error message set")
    
    # Clean up
    for key in ['KRAKEN_MASTER_API_KEY', 'KRAKEN_MASTER_API_SECRET']:
        if key in os.environ:
            del os.environ[key]
    
    # Test Case 3: Invalid credentials (should fail with SDK import or API error)
    print("\n📋 Test Case 3: Invalid Credentials")
    print("-" * 70)
    
    os.environ['KRAKEN_MASTER_API_KEY'] = "invalid_key_12345"
    os.environ['KRAKEN_MASTER_API_SECRET'] = "invalid_secret_67890"
    
    kraken3 = KrakenBroker(account_type=AccountType.MASTER)
    result3 = kraken3.connect()
    
    print(f"Connection result: {result3}")
    print(f"Credentials configured: {kraken3.credentials_configured}")
    print(f"Last connection error: {kraken3.last_connection_error}")
    
    if not result3:
        if kraken3.last_connection_error:
            print(f"✅ PASS: Connection failed with error message: {kraken3.last_connection_error}")
        else:
            print("❌ FAIL: Connection failed but no error message was set!")
            print("This is the bug that should be fixed!")
    else:
        print("⚠️  WARNING: Connection succeeded with invalid credentials (unexpected)")
    
    # Clean up
    for key in ['KRAKEN_MASTER_API_KEY', 'KRAKEN_MASTER_API_SECRET']:
        if key in os.environ:
            del os.environ[key]
    
    print("\n" + "=" * 70)
    print("Test Complete")
    print("=" * 70)

if __name__ == "__main__":
    try:
        test_kraken_error_reporting()
    except Exception as e:
        print(f"\n❌ Test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
