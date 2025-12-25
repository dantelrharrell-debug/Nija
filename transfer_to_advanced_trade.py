#!/usr/bin/env python3
"""
Transfer USDC from Consumer wallet to Advanced Trade portfolio
"""
import os
import sys
sys.path.insert(0, '/usr/src/app/bot')

from coinbase.rest import RESTClient

api_key = os.getenv("COINBASE_API_KEY")
api_secret = os.getenv("COINBASE_API_SECRET", "").replace("\\n", "\n")

print("=" * 80)
print("💸 TRANSFER USDC TO ADVANCED TRADE")
print("=" * 80)

client = RESTClient(api_key=api_key, api_secret=api_secret)

#Get accounts
accounts = client.get_accounts()
accounts_list = getattr(accounts, 'accounts', [])

usdc_account = None
for acc in accounts_list:
    currency = getattr(acc.available_balance, 'currency', 'N/A')
    if currency == 'USDC':
        available = float(getattr(acc.available_balance, 'value', '0'))
        if available > 0:
            usdc_account = acc
            print(f"\n✅ Found USDC: ${available:.2f}")
            print(f"   Account UUID: {acc.uuid}")
            print(f"   Type: {acc.type}")
            break

if not usdc_account:
    print("\n❌ No USDC balance found")
    sys.exit(1)

available_usdc = float(getattr(usdc_account.available_balance, 'value', '0'))

print(f"\n🔄 Transferring ${available_usdc:.2f} USDC to Advanced Trade...")
print("   NOTE: This uses the account deposit endpoint")

try:
    # Transfer to Advanced Trade
    # The Coinbase API uses 'deposit' to move from Consumer → Advanced Trade
    result = client.deposit(
        account_id=usdc_account.uuid,
        amount=str(available_usdc),
        currency="USDC"
    )
    
    print("\n✅ Transfer initiated!")
    print(f"   Result: {result}")
    
except Exception as e:
    print(f"\n❌ Transfer failed: {e}")
    print("\n⚠️  You may need to:")
    print("   1. Transfer manually via Coinbase.com")
    print("   2. Or use the Coinbase mobile app")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 80)
