#!/usr/bin/env python3
"""
Check what happened with APT sale and current balance
"""
import os
from coinbase.rest import RESTClient

def load_env_file():
    if not os.path.exists('.env'):
        return False
    with open('.env', 'r') as f:
        content = f.read()
    current_key = None
    current_value = []
    for line in content.split('\n'):
        if line.startswith('#') or not line.strip():
            continue
        if '=' in line and not line.startswith(' '):
            if current_key:
                os.environ[current_key] = '\n'.join(current_value)
            key, value = line.split('=', 1)
            current_key = key.strip()
            current_value = [value.strip()]
        else:
            if current_key:
                current_value.append(line)
    if current_key:
        os.environ[current_key] = '\n'.join(current_value)
    return True

load_env_file()

print("\n" + "="*80)
print("🔍 CHECKING APT SALE STATUS")
print("="*80)

client = RESTClient(
    api_key=os.getenv('COINBASE_API_KEY'),
    api_secret=os.getenv('COINBASE_API_SECRET')
)

# Check recent orders
print("\n1️⃣ RECENT FILLED ORDERS (Last 10):")
print("-" * 80)

try:
    orders = client.list_orders(limit=10, order_status=['FILLED'])
    order_list = orders.orders if hasattr(orders, 'orders') else []
    
    for order in order_list:
        product = getattr(order, 'product_id', 'UNKNOWN')
        side = getattr(order, 'side', 'UNKNOWN')
        status = getattr(order, 'status', 'UNKNOWN')
        created = getattr(order, 'created_time', '')[:19]
        
        if hasattr(order, 'filled_value'):
            value = float(order.filled_value)
        else:
            value = 0.0
        
        print(f"{created} | {product:12} | {side:4} | {status:10} | ${value:.2f}")
except Exception as e:
    print(f"Error: {e}")

# Check all accounts
print("\n\n2️⃣ ALL ACCOUNTS:")
print("-" * 80)

accounts = client.get_accounts()
account_list = accounts.accounts if hasattr(accounts, 'accounts') else []

total_usd = 0.0
total_crypto = 0.0

for account in account_list:
    currency = account.currency
    
    # Handle dict vs object
    if isinstance(account.available_balance, dict):
        balance = float(account.available_balance.get('value', 0))
    else:
        balance = float(account.available_balance.value)
    
    if balance > 0.0001:
        print(f"{currency:10} {balance:15.8f}")
        
        if currency == 'USD':
            total_usd = balance
        else:
            # Try to get USD value
            try:
                product_id = f"{currency}-USD"
                ticker = client.get_product(product_id)
                price = float(getattr(ticker, 'price', 0))
                value_usd = balance * price
                total_crypto += value_usd
                print(f"           → ${value_usd:.2f} USD")
            except:
                pass

print("\n" + "="*80)
print("📊 SUMMARY")
print("="*80)
print(f"\n💵 Total USD: ${total_usd:.2f}")
print(f"🪙 Total Crypto Value: ${total_crypto:.2f}")
print(f"💰 Total Portfolio: ${total_usd + total_crypto:.2f}")

if total_usd == 0 and total_crypto == 0:
    print("\n🚨 PROBLEM: Both USD and crypto are $0!")
    print("\n💡 Possible reasons:")
    print("   1. APT order is PENDING (not filled yet)")
    print("   2. Funds in Consumer wallet (not Advanced Trade)")
    print("   3. Need to transfer from Consumer → Advanced Trade")
    print("\n🔧 Next steps:")
    print("   1. Check Coinbase.com manually")
    print("   2. Look for pending APT order")
    print("   3. Transfer any USD from Consumer to Advanced Trade")
elif total_usd > 0:
    print(f"\n✅ Ready to trade with ${total_usd:.2f}!")
    print("\n🚀 Start bot:")
    print("   python3 main.py")
elif total_crypto > 0:
    print(f"\n⚠️ Still have ${total_crypto:.2f} in crypto")
    print("   Need to sell for USD first")
