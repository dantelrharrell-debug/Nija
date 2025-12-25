#!/usr/bin/env python3
"""
Check all crypto positions - verify what's actually in the account
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
print("🔍 CHECKING ALL CRYPTO POSITIONS")
print("="*80)

client = RESTClient(
    api_key=os.getenv('COINBASE_API_KEY'),
    api_secret=os.getenv('COINBASE_API_SECRET')
)

# Get all accounts
print("\n📊 Fetching accounts...")
accounts = client.get_accounts()
account_list = accounts.accounts if hasattr(accounts, 'accounts') else accounts.get('accounts', [])

usd_balance = 0.0
crypto_positions = []
total_crypto_value = 0.0

print("\n" + "-"*80)
print("ACCOUNT BREAKDOWN:")
print("-"*80)

for account in account_list:
    currency = account.currency
    
    if isinstance(account.available_balance, dict):
        balance = float(account.available_balance.get('value', 0))
    else:
        balance = float(account.available_balance.value)
    
    if currency == 'USD':
        usd_balance = balance
        print(f"\n💵 USD: ${balance:.2f}")
        continue
    
    if balance > 0.00000001:
        try:
            ticker = client.get_product(f"{currency}-USD")
            price = float(getattr(ticker, 'price', 0))
            value = balance * price
            
            crypto_positions.append({
                'currency': currency,
                'balance': balance,
                'price': price,
                'value': value
            })
            total_crypto_value += value
            
            print(f"\n🪙 {currency}:")
            print(f"   Balance: {balance:.8f}")
            print(f"   Price:   ${price:.2f}")
            print(f"   Value:   ${value:.2f}")
            
        except Exception as e:
            print(f"\n⚠️  {currency}: {balance:.8f} (could not get price)")

print("\n" + "="*80)
print("PORTFOLIO SUMMARY")
print("="*80)

print(f"\n💵 USD Cash:        ${usd_balance:.2f}")
print(f"🪙 Crypto Value:    ${total_crypto_value:.2f}")
print(f"💰 Total:           ${usd_balance + total_crypto_value:.2f}")

print(f"\n📊 Number of crypto positions: {len(crypto_positions)}")

if crypto_positions:
    print("\n" + "="*80)
    print("⚠️  POSITIONS NEED TO BE SOLD")
    print("="*80)
    
    print("\nYou have unsold crypto. To liquidate:")
    print("   1. Run: python3 sell_all_positions.py")
    print("      (This requires typing 'SELL ALL' to confirm)")
    print("\n   2. Or run: python3 emergency_liquidate.py")
    print("      (For immediate liquidation without confirmation)")
else:
    print("\n✅ No crypto positions - all funds in USD")

print("\n" + "="*80 + "\n")
