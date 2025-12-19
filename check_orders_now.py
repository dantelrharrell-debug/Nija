#!/usr/bin/env python3
"""
Direct check with proper .env loading
"""
import os
import re

# Load .env file manually (handle multiline PEM)
def load_env_file():
    if not os.path.exists('.env'):
        print("❌ .env file not found")
        return False
    
    with open('.env', 'r') as f:
        content = f.read()
    
    # Parse environment variables (handle multiline values)
    current_key = None
    current_value = []
    
    for line in content.split('\n'):
        # Skip comments and empty lines
        if line.startswith('#') or not line.strip():
            continue
        
        # Check if this is a new key=value pair
        if '=' in line and not line.startswith(' '):
            # Save previous key if exists
            if current_key:
                os.environ[current_key] = '\n'.join(current_value)
            
            # Start new key
            key, value = line.split('=', 1)
            current_key = key.strip()
            current_value = [value.strip()]
        else:
            # Continuation of previous value (multiline)
            if current_key:
                current_value.append(line)
    
    # Save last key
    if current_key:
        os.environ[current_key] = '\n'.join(current_value)
    
    return True

# Load environment
if load_env_file():
    print("✅ Loaded .env file\n")
else:
    print("❌ Could not load .env file\n")
    exit(1)

# Now import and run the check
from coinbase.rest import RESTClient

def main():
    print("="*80)
    print("🚨 WHAT'S DRAINING YOUR ACCOUNT?")
    print("="*80)
    
    api_key = os.getenv('COINBASE_API_KEY')
    api_secret = os.getenv('COINBASE_API_SECRET')
    
    print(f"\n🔐 Credentials check:")
    print(f"   API Key: {'✅ Found' if api_key else '❌ Missing'}")
    print(f"   API Secret: {'✅ Found (' + str(len(api_secret)) + ' chars)' if api_secret else '❌ Missing'}")
    
    if not api_key or not api_secret:
        print("\n❌ Cannot proceed without credentials")
        return
    
    try:
        print("\n🔌 Connecting to Coinbase...")
        client = RESTClient(api_key=api_key, api_secret=api_secret)
        print("✅ Connected!\n")
        
        # Check open orders
        print("1️⃣ CHECKING FOR OPEN/PENDING ORDERS...")
        print("-" * 80)
        
        try:
            open_orders = client.list_orders(limit=100, order_status=['OPEN', 'PENDING'])
            order_list = open_orders.orders if hasattr(open_orders, 'orders') else []
            
            if order_list:
                print(f"\n🚨 FOUND {len(order_list)} OPEN ORDERS!\n")
                print("⚠️  These execute IMMEDIATELY when you deposit money!\n")
                
                for order in order_list:
                    product_id = getattr(order, 'product_id', 'UNKNOWN')
                    side = getattr(order, 'side', 'UNKNOWN')
                    order_id = getattr(order, 'order_id', 'UNKNOWN')[:20]
                    print(f"   🔴 {product_id:15} | {side:4} | ID: {order_id}...")
                
                print("\n   ⚠️  THIS IS WHY YOUR $5 DISAPPEARS!")
                print("   → Need to CANCEL these orders")
            else:
                print("   ✅ No open orders")
        except Exception as e:
            print(f"   Error: {e}")
        
        # Check recent filled orders
        print("\n\n2️⃣ RECENT FILLED ORDERS (Last 50)...")
        print("-" * 80)
        
        try:
            filled = client.list_orders(limit=50, order_status=['FILLED'])
            order_list = filled.orders if hasattr(filled, 'orders') else []
            
            if not order_list:
                print("   ℹ️  No filled orders")
            else:
                print(f"\n   Found {len(order_list)} filled orders:\n")
                
                total_buy = 0.0
                total_sell = 0.0
                
                for i, order in enumerate(order_list[:20], 1):
                    product_id = getattr(order, 'product_id', 'UNKNOWN')
                    side = getattr(order, 'side', 'UNKNOWN')
                    filled_value = float(getattr(order, 'filled_value', 0))
                    created_time = getattr(order, 'created_time', '')[:19]
                    
                    print(f"   {i:2}. {created_time} | {product_id:15} | {side:4} | ${filled_value:8.2f}")
                    
                    if side == 'BUY':
                        total_buy += filled_value
                    else:
                        total_sell += filled_value
                
                print(f"\n   BUY:  ${total_buy:,.2f} spent")
                print(f"   SELL: ${total_sell:,.2f} received")
                print(f"   Net:  ${total_sell - total_buy:+,.2f}")
                
                if total_sell < total_buy:
                    print(f"\n   ❌ LOSING: ${total_buy - total_sell:.2f}")
                    print("   Your trades lost money - that's where it went!")
        except Exception as e:
            print(f"   Error: {e}")
        
        # Check balance
        print("\n\n3️⃣ CURRENT BALANCE...")
        print("-" * 80)
        
        try:
            accounts = client.get_accounts()
            account_list = accounts.accounts if hasattr(accounts, 'accounts') else []
            
            usd_balance = 0.0
            crypto_holdings = []
            
            for account in account_list:
                balance = float(account.available_balance.value)
                currency = account.currency
                
                if currency == 'USD':
                    usd_balance = balance
                elif balance > 0:
                    crypto_holdings.append(f"{currency}: {balance:.8f}")
            
            print(f"   USD Balance: ${usd_balance:.2f}")
            
            if crypto_holdings:
                print(f"\n   Crypto Holdings:")
                for holding in crypto_holdings[:10]:
                    print(f"   • {holding}")
                
                print(f"\n   ℹ️  Your $5 became crypto (see above)")
        except Exception as e:
            print(f"   Error: {e}")
        
        print("\n\n" + "="*80)
        print("💡 SOLUTION")
        print("="*80)
        print("\n1. CANCEL open orders (if any above)")
        print("2. STOP depositing $5 (too small for fees)")
        print("3. DEPOSIT $50-100 instead")
        print("4. Bot can then take $10-20 positions (profitable after fees)")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
