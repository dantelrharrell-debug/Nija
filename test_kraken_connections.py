#!/usr/bin/env python3
"""
Test Kraken Connections for Master and All Users
Verifies that Kraken is properly configured and connected for:
- Master account
- User #1 (Daivon Frazier)  
- User #2 (Tania Gilbert)
"""

import os
import sys
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

from bot.broker_manager import KrakenBroker, BrokerType, AccountType

def test_connection(account_name, account_type, user_id=None):
    """Test connection for a specific account"""
    print(f"\n{'='*70}")
    print(f"🔌 Testing {account_name}")
    print(f"{'='*70}")
    
    try:
        if account_type == AccountType.MASTER:
            broker = KrakenBroker(account_type=AccountType.MASTER)
        else:
            broker = KrakenBroker(account_type=AccountType.USER, user_id=user_id)
        
        print(f"✅ Broker instance created for {account_name}")
        
        # Try to connect
        print(f"⏳ Connecting to Kraken Pro...")
        if broker.connect():
            print(f"✅ {account_name} connected successfully!")
            
            # Get balance
            try:
                balance = broker.get_account_balance()
                print(f"💰 Balance: ${balance:,.2f}")
                
                if balance > 0:
                    print(f"✅ Account is funded and ready to trade")
                else:
                    print(f"⚠️  Account has zero balance - needs funding to trade")
                
                return True
            except Exception as bal_err:
                print(f"⚠️  Connected but could not get balance: {bal_err}")
                return True
        else:
            print(f"❌ {account_name} connection failed")
            return False
            
    except Exception as e:
        print(f"❌ Error testing {account_name}: {e}")
        import traceback
        print(traceback.format_exc())
        return False

def main():
    print("="*70)
    print("🔍 KRAKEN CONNECTION TEST - MASTER + ALL USERS")
    print("="*70)
    print()
    
    results = {}
    
    # Test Master account
    results['master'] = test_connection("MASTER ACCOUNT", AccountType.MASTER)
    
    # Test User #1 (Daivon Frazier)
    results['user1'] = test_connection("USER #1 (Daivon Frazier)", AccountType.USER, user_id="daivon_frazier")
    
    # Test User #2 (Tania Gilbert)
    results['user2'] = test_connection("USER #2 (Tania Gilbert)", AccountType.USER, user_id="tania_gilbert")
    
    # Summary
    print(f"\n{'='*70}")
    print("📊 SUMMARY")
    print(f"{'='*70}")
    
    total = len(results)
    connected = sum(1 for v in results.values() if v)
    
    print(f"\n✅ Connected: {connected}/{total}")
    print(f"❌ Failed: {total - connected}/{total}")
    
    if results['master']:
        print(f"✅ Master account: CONNECTED")
    else:
        print(f"❌ Master account: NOT CONNECTED")
    
    if results['user1']:
        print(f"✅ User #1 (Daivon): CONNECTED")
    else:
        print(f"❌ User #1 (Daivon): NOT CONNECTED")
    
    if results['user2']:
        print(f"✅ User #2 (Tania): CONNECTED")
    else:
        print(f"❌ User #2 (Tania): NOT CONNECTED")
    
    print()
    
    if connected == total:
        print("🎉 ALL ACCOUNTS CONNECTED - Ready for multi-account trading!")
        return 0
    elif connected > 0:
        print("⚠️  PARTIAL CONNECTION - Some accounts failed")
        return 1
    else:
        print("❌ NO ACCOUNTS CONNECTED - Check credentials and API permissions")
        return 2

if __name__ == "__main__":
    sys.exit(main())
