#!/usr/bin/env python3
"""
Final bleeding status check - simple and direct
"""
import os
from dotenv import load_dotenv
load_dotenv()

from coinbase.rest import RESTClient

print("\n" + "="*60)
print("FINAL BLEEDING CHECK")
print("="*60 + "\n")

client = RESTClient(
    api_key=os.getenv('COINBASE_API_KEY'),
    api_secret=os.getenv('COINBASE_API_SECRET')
)

accounts = client.get_accounts()
accounts = getattr(accounts, 'accounts', [])

print("CURRENT HOLDINGS:\n")

crypto_found = False
cash_total = 0

for account in accounts:
    currency = getattr(account, 'currency', None)
    available = getattr(account, 'available_balance', None)
    
    if not currency:
        continue
    
    if hasattr(available, 'value'):
        balance = float(available.value)
    else:
        balance = 0
    
    if balance > 0.001:
        if currency in ['USD', 'USDC']:
            cash_total += balance
            print(f"💵 {currency}: ${balance:.2f}")
        else:
            crypto_found = True
            print(f"🪙 {currency}: {balance:.8f} ← BLEEDING!")

print("\n" + "="*60)
if crypto_found:
    print("❌ STILL BLEEDING - Crypto holdings remain!")
else:
    print(f"✅ BLEEDING STOPPED - No crypto left!")
    print(f"✅ All cash: ${cash_total:.2f}")
print("="*60 + "\n")
