#!/usr/bin/env python3
"""
Verify User #1 Kraken Trading Configuration

This script checks if User #1 (Daivon Frazier) is properly configured
for Kraken trading and will be picked up by the independent trader.

Checks:
1. Kraken SDK installed
2. User #1 credentials configured
3. Kraken connection works
4. Multi-account manager initialization
5. Independent trader will detect user #1
"""

import os
import sys

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def check_sdk():
    """Check if Kraken SDK is installed"""
    print("=" * 80)
    print("STEP 1: Checking Kraken SDK Installation")
    print("=" * 80)
    
    try:
        import krakenex
        import pykrakenapi
        print("✅ krakenex installed")
        print("✅ pykrakenapi installed")
        return True
    except ImportError as e:
        print(f"❌ Kraken SDK not installed: {e}")
        print("\nInstall with:")
        print("  pip install krakenex==2.2.2 pykrakenapi==0.3.2")
        return False


def check_credentials():
    """Check if User #1 Kraken credentials are configured"""
    print("\n" + "=" * 80)
    print("STEP 2: Checking User #1 Credentials")
    print("=" * 80)
    
    api_key = os.getenv("KRAKEN_USER_DAIVON_API_KEY", "").strip()
    api_secret = os.getenv("KRAKEN_USER_DAIVON_API_SECRET", "").strip()
    
    if not api_key:
        print("❌ KRAKEN_USER_DAIVON_API_KEY not set")
        print("\nAdd to .env file:")
        print("  KRAKEN_USER_DAIVON_API_KEY=<your-api-key>")
        return False
    
    if not api_secret:
        print("❌ KRAKEN_USER_DAIVON_API_SECRET not set")
        print("\nAdd to .env file:")
        print("  KRAKEN_USER_DAIVON_API_SECRET=<your-api-secret>")
        return False
    
    print(f"✅ KRAKEN_USER_DAIVON_API_KEY set ({len(api_key)} characters)")
    print(f"✅ KRAKEN_USER_DAIVON_API_SECRET set ({len(api_secret)} characters)")
    return True


def check_connection():
    """Test Kraken connection for User #1"""
    print("\n" + "=" * 80)
    print("STEP 3: Testing Kraken Connection")
    print("=" * 80)
    
    try:
        import krakenex
        
        api_key = os.getenv("KRAKEN_USER_DAIVON_API_KEY", "").strip()
        api_secret = os.getenv("KRAKEN_USER_DAIVON_API_SECRET", "").strip()
        
        api = krakenex.API(key=api_key, secret=api_secret)
        print("⏳ Querying Kraken API...")
        
        balance = api.query_private('Balance')
        
        if balance and 'error' in balance and balance['error']:
            error_msgs = ', '.join(balance['error'])
            print(f"❌ Kraken API error: {error_msgs}")
            return False, None
        
        if balance and 'result' in balance:
            result = balance.get('result', {})
            usd = float(result.get('ZUSD', 0))
            usdt = float(result.get('USDT', 0))
            total = usd + usdt
            
            print("\n✅ KRAKEN CONNECTION SUCCESSFUL")
            print(f"   USD:  ${usd:.2f}")
            print(f"   USDT: ${usdt:.2f}")
            print(f"   Total: ${total:.2f}")
            return True, total
        
        print("❌ Unexpected Kraken API response")
        return False, None
        
    except Exception as e:
        print(f"❌ Connection error: {e}")
        return False, None


def check_multi_account_manager():
    """Check if multi-account broker manager can initialize User #1"""
    print("\n" + "=" * 80)
    print("STEP 4: Testing Multi-Account Manager")
    print("=" * 80)
    
    try:
        from multi_account_broker_manager import MultiAccountBrokerManager
        from broker_manager import BrokerType
        
        manager = MultiAccountBrokerManager()
        print("✅ MultiAccountBrokerManager imported")
        
        # Try to add User #1 broker
        print("⏳ Attempting to add User #1 Kraken broker...")
        user1_broker = manager.add_user_broker("daivon_frazier", BrokerType.KRAKEN)
        
        if user1_broker:
            print("✅ User #1 Kraken broker connected successfully")
            try:
                balance = user1_broker.get_account_balance()
                print(f"   User #1 balance: ${balance:,.2f}")
                return True, balance
            except Exception as e:
                print(f"   ⚠️  Could not get balance: {e}")
                return True, 0
        else:
            print("❌ Failed to connect User #1 Kraken broker")
            return False, None
            
    except Exception as e:
        print(f"❌ Error initializing multi-account manager: {e}")
        import traceback
        traceback.print_exc()
        return False, None


def check_independent_trader_detection():
    """Check if independent trader will detect User #1"""
    print("\n" + "=" * 80)
    print("STEP 5: Testing Independent Trader Detection")
    print("=" * 80)
    
    try:
        from independent_broker_trader import IndependentBrokerTrader
        from broker_manager import BrokerManager
        from multi_account_broker_manager import MultiAccountBrokerManager
        from broker_manager import BrokerType
        
        # Create managers
        broker_manager = BrokerManager()
        multi_account_manager = MultiAccountBrokerManager()
        
        # Add User #1 broker
        print("⏳ Adding User #1 Kraken broker...")
        user1_broker = multi_account_manager.add_user_broker("daivon_frazier", BrokerType.KRAKEN)
        
        if not user1_broker:
            print("❌ Could not add User #1 broker")
            return False
        
        print("✅ User #1 broker added")
        
        # Create a minimal trading strategy mock
        class MockStrategy:
            def __init__(self):
                self.broker = None
                self.user1_broker = None
            
            def run_cycle(self):
                pass
        
        mock_strategy = MockStrategy()
        
        # Create independent trader
        print("⏳ Initializing independent trader...")
        trader = IndependentBrokerTrader(
            broker_manager,
            mock_strategy,
            multi_account_manager
        )
        
        print("✅ Independent trader initialized")
        
        # Detect funded user brokers
        print("⏳ Detecting funded user brokers...")
        funded_users = trader.detect_funded_user_brokers()
        
        if "daivon_frazier" in funded_users:
            print("\n✅ USER #1 DETECTED AS FUNDED!")
            print(f"   Funded brokers: {list(funded_users['daivon_frazier'].keys())}")
            for broker_name, balance in funded_users['daivon_frazier'].items():
                print(f"   {broker_name}: ${balance:,.2f}")
            return True
        else:
            print("\n❌ User #1 NOT detected as funded")
            if funded_users:
                print(f"   Other funded users: {list(funded_users.keys())}")
            else:
                print("   No funded users detected")
            return False
            
    except Exception as e:
        print(f"❌ Error testing independent trader: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all verification checks"""
    print("\n" + "=" * 80)
    print("NIJA USER #1 KRAKEN TRADING VERIFICATION")
    print("=" * 80)
    print("\nUser: Daivon Frazier (daivon_frazier)")
    print("Broker: Kraken Pro")
    print("=" * 80)
    
    results = {
        'sdk': False,
        'credentials': False,
        'connection': False,
        'multi_account': False,
        'independent_trader': False
    }
    
    balances = {}
    
    # Run checks
    results['sdk'] = check_sdk()
    
    if results['sdk']:
        results['credentials'] = check_credentials()
    
    if results['credentials']:
        connected, balance = check_connection()
        results['connection'] = connected
        if balance is not None:
            balances['api_direct'] = balance
    
    if results['connection']:
        multi_ok, balance = check_multi_account_manager()
        results['multi_account'] = multi_ok
        if balance is not None:
            balances['multi_account'] = balance
    
    if results['multi_account']:
        results['independent_trader'] = check_independent_trader_detection()
    
    # Summary
    print("\n" + "=" * 80)
    print("VERIFICATION SUMMARY")
    print("=" * 80)
    
    total = len(results)
    passed = sum(1 for r in results.values() if r)
    
    for check, result in results.items():
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status} - {check.replace('_', ' ').title()}")
    
    print("\n" + "-" * 80)
    print(f"Overall: {passed}/{total} checks passed")
    print("-" * 80)
    
    if balances:
        print("\nBalances detected:")
        for source, balance in balances.items():
            print(f"  {source}: ${balance:,.2f}")
    
    print("\n" + "=" * 80)
    
    if all(results.values()):
        print("🎉 SUCCESS: User #1 is ready for Kraken trading!")
        print("=" * 80)
        print("\nWhen the bot starts, User #1's Kraken account will:")
        print("  • Trade independently in its own thread")
        print("  • Use its own balance and positions")
        print("  • Execute trades separately from master account")
        print("  • Run the same APEX v7.1 strategy")
        print("\nTo start trading:")
        print("  ./start.sh")
        print("\nOr deploy to Railway/Render with environment variables set.")
        return 0
    else:
        print("⚠️  INCOMPLETE: Some checks failed")
        print("=" * 80)
        print("\nFix the failed checks above before User #1 can trade on Kraken.")
        
        if not results['sdk']:
            print("\n1. Install Kraken SDK:")
            print("   pip install krakenex==2.2.2 pykrakenapi==0.3.2")
        
        if not results['credentials']:
            print("\n2. Set User #1 credentials in .env:")
            print("   KRAKEN_USER_DAIVON_API_KEY=<your-api-key>")
            print("   KRAKEN_USER_DAIVON_API_SECRET=<your-api-secret>")
        
        if not results['connection']:
            print("\n3. Verify Kraken API credentials are valid")
            print("   - Check https://www.kraken.com/u/security/api")
            print("   - Ensure API key has required permissions")
        
        return 1


if __name__ == "__main__":
    sys.exit(main())
