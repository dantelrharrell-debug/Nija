#!/usr/bin/env python3
"""
Test script for Kraken credential validation improvements.

This tests the enhanced detection of malformed credentials (set but containing only whitespace).
"""

import os
import sys
import logging

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s:%(name)s:%(message)s')

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

from broker_manager import KrakenBroker, AccountType

def test_scenario(scenario_name, env_vars):
    """Test a specific credential scenario"""
    print("\n" + "="*80)
    print(f"TEST SCENARIO: {scenario_name}")
    print("="*80)
    
    # Clear existing env vars
    for key in ['KRAKEN_MASTER_API_KEY', 'KRAKEN_MASTER_API_SECRET']:
        if key in os.environ:
            del os.environ[key]
    
    # Set test env vars
    for key, value in env_vars.items():
        os.environ[key] = value
        print(f"Setting {key} = {repr(value)}")
    
    # Try to connect
    print("\nAttempting to connect...")
    broker = KrakenBroker(account_type=AccountType.MASTER)
    result = broker.connect()
    
    print(f"Connection result: {result}")
    return result

def main():
    """Run all test scenarios"""
    print("Testing Kraken Credential Validation")
    print("="*80)
    
    # Test 1: No credentials
    test_scenario(
        "No credentials set",
        {}
    )
    
    # Test 2: Valid credentials (fake but properly formatted)
    test_scenario(
        "Valid credentials (fake but properly formatted)",
        {
            'KRAKEN_MASTER_API_KEY': 'test_api_key_12345',
            'KRAKEN_MASTER_API_SECRET': 'test_secret_67890abcdef'
        }
    )
    
    # Test 3: Credentials with only whitespace
    test_scenario(
        "Credentials with only whitespace",
        {
            'KRAKEN_MASTER_API_KEY': '   ',
            'KRAKEN_MASTER_API_SECRET': '\t\n'
        }
    )
    
    # Test 4: Credentials with leading/trailing whitespace (should work)
    test_scenario(
        "Credentials with leading/trailing whitespace (should be trimmed)",
        {
            'KRAKEN_MASTER_API_KEY': '  test_api_key_12345  ',
            'KRAKEN_MASTER_API_SECRET': '\ntest_secret_67890abcdef\t'
        }
    )
    
    # Test 5: Only API key is whitespace
    test_scenario(
        "API key is whitespace, secret is valid",
        {
            'KRAKEN_MASTER_API_KEY': '   ',
            'KRAKEN_MASTER_API_SECRET': 'test_secret_67890abcdef'
        }
    )
    
    # Test 6: Only API secret is whitespace
    test_scenario(
        "API key is valid, secret is whitespace",
        {
            'KRAKEN_MASTER_API_KEY': 'test_api_key_12345',
            'KRAKEN_MASTER_API_SECRET': '   '
        }
    )
    
    print("\n" + "="*80)
    print("All test scenarios completed!")
    print("="*80)
    
    # Clean up
    for key in ['KRAKEN_MASTER_API_KEY', 'KRAKEN_MASTER_API_SECRET']:
        if key in os.environ:
            del os.environ[key]

if __name__ == '__main__':
    main()
