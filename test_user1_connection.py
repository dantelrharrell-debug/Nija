#!/usr/bin/env python3
"""
Test script to verify User #1 Kraken connection works properly.
This simulates the initialization process in trading_strategy.py
"""

import os
import sys

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

# Load environment variables
try:
    from dotenv import load_dotenv
    # Use relative path for .env file
    env_path = os.path.join(os.path.dirname(__file__), '.env')
    load_dotenv(dotenv_path=env_path)
    print("✅ Environment variables loaded")
except ImportError:
    print("⚠️  python-dotenv not available, using system environment")

def test_kraken_sdk():
    """Test if Kraken SDK is available."""
    try:
        import krakenex
        import pykrakenapi
        print("✅ Kraken SDK modules imported successfully")
        return True
    except ImportError as e:
        print(f"❌ Kraken SDK import failed: {e}")
        return False

def test_credentials():
    """Test if User #1 Kraken credentials are configured."""
    key = os.getenv('KRAKEN_USER_DAIVON_API_KEY', '')
    secret = os.getenv('KRAKEN_USER_DAIVON_API_SECRET', '')
    
    if key and secret:
        print(f"✅ User #1 Kraken credentials configured")
        print(f"   API Key: {len(key)} characters")
        print(f"   API Secret: {len(secret)} characters")
        return True
    else:
        print("❌ User #1 Kraken credentials missing")
        if not key:
            print("   Missing: KRAKEN_USER_DAIVON_API_KEY")
        if not secret:
            print("   Missing: KRAKEN_USER_DAIVON_API_SECRET")
        return False

def test_broker_connection():
    """Test if KrakenBroker can be instantiated and connect for User #1."""
    try:
        from broker_manager import KrakenBroker, BrokerType, AccountType
        
        print("\n📊 Testing Kraken broker connection for User #1...")
        
        # Create broker instance for user account
        user_id = "daivon_frazier"
        broker = KrakenBroker(account_type=AccountType.USER, user_id=user_id)
        
        print(f"✅ KrakenBroker instance created for user: {user_id}")
        
        # Try to connect
        if broker.connect():
            print(f"✅ User #1 Kraken broker connected successfully")
            
            # Try to get balance
            try:
                balance = broker.get_account_balance()
                print(f"✅ User #1 Kraken balance: ${balance:,.2f}")
                return True
            except Exception as bal_err:
                print(f"⚠️  Could not get balance: {bal_err}")
                return True  # Connection worked even if balance check failed
        else:
            print(f"❌ User #1 Kraken broker connection failed")
            return False
            
    except ImportError as ie:
        print(f"❌ Import error: {ie}")
        print("   Required modules not available. Check requirements.txt installation.")
        return False
    except Exception as e:
        print(f"❌ Broker connection test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_multi_account_manager():
    """Test if MultiAccountBrokerManager can add User #1."""
    try:
        from multi_account_broker_manager import MultiAccountBrokerManager
        from broker_manager import BrokerType
        
        print("\n🔷 Testing MultiAccountBrokerManager...")
        
        manager = MultiAccountBrokerManager()
        print("✅ MultiAccountBrokerManager created")
        
        # Add user broker
        user_id = "daivon_frazier"
        user1_broker = manager.add_user_broker(user_id, BrokerType.KRAKEN)
        
        if user1_broker:
            print(f"✅ User #1 broker added to MultiAccountBrokerManager")
            
            # Get balance through manager
            try:
                balance = manager.get_user_balance(user_id, BrokerType.KRAKEN)
                print(f"✅ User #1 balance via manager: ${balance:,.2f}")
            except Exception as bal_err:
                print(f"⚠️  Could not get balance via manager: {bal_err}")
            
            return True
        else:
            print(f"❌ Failed to add User #1 broker to MultiAccountBrokerManager")
            return False
            
    except Exception as e:
        print(f"❌ MultiAccountBrokerManager test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Run all tests."""
    print("=" * 80)
    print("USER #1 KRAKEN CONNECTION TEST")
    print("=" * 80)
    print()
    
    # Test 1: SDK
    print("TEST 1: Kraken SDK Availability")
    print("-" * 80)
    sdk_ok = test_kraken_sdk()
    print()
    
    # Test 2: Credentials
    print("TEST 2: User #1 Credentials")
    print("-" * 80)
    creds_ok = test_credentials()
    print()
    
    if not (sdk_ok and creds_ok):
        print("=" * 80)
        print("❌ PREREQUISITES NOT MET")
        print("=" * 80)
        print("Cannot proceed with connection tests.")
        print("Please install Kraken SDK and configure credentials.")
        return 1
    
    # Test 3: Direct broker connection
    print("TEST 3: Direct Broker Connection")
    print("-" * 80)
    broker_ok = test_broker_connection()
    print()
    
    # Test 4: Multi-account manager
    print("TEST 4: Multi-Account Manager")
    print("-" * 80)
    manager_ok = test_multi_account_manager()
    print()
    
    # Summary
    print("=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)
    print(f"Kraken SDK:                {'✅ PASS' if sdk_ok else '❌ FAIL'}")
    print(f"User #1 Credentials:       {'✅ PASS' if creds_ok else '❌ FAIL'}")
    print(f"Direct Broker Connection:  {'✅ PASS' if broker_ok else '❌ FAIL'}")
    print(f"Multi-Account Manager:     {'✅ PASS' if manager_ok else '❌ FAIL'}")
    print()
    
    if sdk_ok and creds_ok and broker_ok and manager_ok:
        print("✅ ALL TESTS PASSED")
        print()
        print("User #1 (Daivon Frazier) CAN trade on Kraken.")
        print("The bot should be able to start trading for User #1 successfully.")
        print()
        return 0
    else:
        print("❌ SOME TESTS FAILED")
        print()
        print("User #1 trading may not work properly.")
        print("Review the test results above and fix the failing components.")
        print()
        return 1

if __name__ == "__main__":
    sys.exit(main())
