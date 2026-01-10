#!/usr/bin/env python3
"""
Verify that Masters Alpaca, Kraken, and Coinbase are all trading.
This script checks the multi-account manager status and confirms proper registration.

Run this after deploying the fix to verify all three master brokers are active.
"""

import os
import sys
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

print("=" * 80)
print("MASTER BROKERS TRADING STATUS VERIFICATION")
print("=" * 80)
print()

try:
    print("📋 Step 1: Importing required modules...")
    from broker_manager import BrokerType
    from multi_account_broker_manager import MultiAccountBrokerManager
    print("   ✅ Modules imported successfully")
    print()
    
    print("📋 Step 2: Checking what SHOULD be registered...")
    expected_master_brokers = [
        BrokerType.COINBASE,
        BrokerType.KRAKEN,
        BrokerType.ALPACA
    ]
    
    print("   Expected MASTER brokers:")
    for broker_type in expected_master_brokers:
        print(f"      • {broker_type.value.upper()}")
    print()
    
    print("📋 Step 3: Simulating broker initialization (safe - no trading)...")
    print("   Note: This creates a fresh MultiAccountBrokerManager to test")
    print("   the registration logic without starting actual trading.")
    print()
    
    manager = MultiAccountBrokerManager()
    
    # Try to add each master broker
    results = {}
    
    print("🔵 Testing Coinbase MASTER registration...")
    try:
        coinbase = manager.add_master_broker(BrokerType.COINBASE)
        if coinbase:
            results['coinbase'] = {
                'status': 'connected',
                'registered': BrokerType.COINBASE in manager.master_brokers,
                'balance': None
            }
            try:
                balance = coinbase.get_account_balance()
                results['coinbase']['balance'] = balance
                print(f"   ✅ Coinbase MASTER connected (Balance: ${balance:,.2f})")
            except Exception as bal_err:
                print(f"   ✅ Coinbase MASTER connected (Balance: Unable to fetch - {bal_err})")
                results['coinbase']['balance'] = 0.0
        else:
            results['coinbase'] = {'status': 'failed', 'registered': False, 'balance': None}
            print("   ❌ Coinbase MASTER connection failed")
    except Exception as e:
        results['coinbase'] = {'status': 'error', 'registered': False, 'balance': None}
        print(f"   ❌ Coinbase MASTER error: {e}")
    
    print()
    print("🟣 Testing Kraken MASTER registration...")
    try:
        kraken = manager.add_master_broker(BrokerType.KRAKEN)
        if kraken:
            results['kraken'] = {
                'status': 'connected',
                'registered': BrokerType.KRAKEN in manager.master_brokers,
                'balance': None
            }
            try:
                balance = kraken.get_account_balance()
                results['kraken']['balance'] = balance
                print(f"   ✅ Kraken MASTER connected (Balance: ${balance:,.2f})")
            except Exception as bal_err:
                print(f"   ✅ Kraken MASTER connected (Balance: Unable to fetch - {bal_err})")
                results['kraken']['balance'] = 0.0
        else:
            results['kraken'] = {'status': 'failed', 'registered': False, 'balance': None}
            print("   ❌ Kraken MASTER connection failed")
    except Exception as e:
        results['kraken'] = {'status': 'error', 'registered': False, 'balance': None}
        print(f"   ❌ Kraken MASTER error: {e}")
    
    print()
    print("🟡 Testing Alpaca MASTER registration...")
    try:
        alpaca = manager.add_master_broker(BrokerType.ALPACA)
        if alpaca:
            results['alpaca'] = {
                'status': 'connected',
                'registered': BrokerType.ALPACA in manager.master_brokers,
                'balance': None
            }
            try:
                balance = alpaca.get_account_balance()
                results['alpaca']['balance'] = balance
                print(f"   ✅ Alpaca MASTER connected (Balance: ${balance:,.2f})")
            except Exception as bal_err:
                print(f"   ✅ Alpaca MASTER connected (Balance: Unable to fetch - {bal_err})")
                results['alpaca']['balance'] = 0.0
        else:
            results['alpaca'] = {'status': 'failed', 'registered': False, 'balance': None}
            print("   ❌ Alpaca MASTER connection failed")
    except Exception as e:
        results['alpaca'] = {'status': 'error', 'registered': False, 'balance': None}
        print(f"   ❌ Alpaca MASTER error: {e}")
    
    print()
    print("📋 Step 4: Checking multi-account manager registration...")
    print()
    print("   Registered MASTER brokers:")
    if manager.master_brokers:
        for broker_type in manager.master_brokers.keys():
            print(f"      ✅ {broker_type.value.upper()}")
    else:
        print("      ❌ No MASTER brokers registered")
    
    print()
    print("=" * 80)
    print("VERIFICATION SUMMARY")
    print("=" * 80)
    print()
    
    # Check each expected broker
    all_connected = True
    all_registered = True
    
    for broker_name in ['coinbase', 'kraken', 'alpaca']:
        if broker_name in results:
            result = results[broker_name]
            status = result['status']
            registered = result['registered']
            balance = result['balance']
            
            broker_display = broker_name.upper()
            
            print(f"🔸 {broker_display} MASTER:")
            print(f"   Connection: {'✅ CONNECTED' if status == 'connected' else '❌ FAILED'}")
            print(f"   Registered: {'✅ YES' if registered else '❌ NO'}")
            
            if balance is not None:
                print(f"   Balance: ${balance:,.2f}")
                if balance < 2.0 and broker_name != 'alpaca':
                    print(f"   ⚠️  Warning: Balance below minimum ($2.00) - may not trade")
            else:
                print(f"   Balance: N/A")
            
            if status != 'connected':
                all_connected = False
            if not registered:
                all_registered = False
            
            print()
    
    print("=" * 80)
    
    if all_connected and all_registered:
        print("✅ SUCCESS: All three MASTER brokers are connected and registered!")
        print()
        print("Expected behavior:")
        print("   • Coinbase MASTER will trade cryptocurrencies")
        print("   • Kraken MASTER will trade cryptocurrencies")  
        print("   • Alpaca MASTER will trade stocks (paper trading)")
        print()
        print("Next steps:")
        print("   1. Deploy the bot to production")
        print("   2. Monitor logs for trading activity")
        print("   3. Check broker dashboards for executed trades")
        sys.exit(0)
    else:
        print("❌ ISSUES FOUND:")
        if not all_connected:
            print("   • Not all brokers connected successfully")
            print("   • Check credentials in .env file")
            print("   • Verify API keys are valid and not expired")
            print("   • Check API permissions (read, write, trade)")
        if not all_registered:
            print("   • Not all brokers registered in multi-account manager")
            print("   • This suggests a code issue - check trading_strategy.py")
        print()
        print("Review the errors above and fix before deploying.")
        sys.exit(1)

except ImportError as e:
    print(f"❌ Import error: {e}")
    print()
    print("This is likely because:")
    print("   1. Required Python packages are not installed")
    print("   2. You're not in the Nija root directory")
    print()
    print("Install dependencies: pip install -r requirements.txt")
    sys.exit(1)
except Exception as e:
    print(f"❌ Unexpected error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
