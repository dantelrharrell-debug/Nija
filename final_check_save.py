#!/usr/bin/env python3
"""
Final bleeding check - saves output to file
"""
import os
from dotenv import load_dotenv
load_dotenv()

from coinbase.rest import RESTClient

output = []
output.append("\n" + "="*60)
output.append("FINAL BLEEDING CHECK")
output.append("="*60 + "\n")

try:
    client = RESTClient(
        api_key=os.getenv('COINBASE_API_KEY'),
        api_secret=os.getenv('COINBASE_API_SECRET')
    )

    accounts = client.get_accounts()
    accounts = getattr(accounts, 'accounts', [])

    output.append("CURRENT HOLDINGS:\n")

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
                output.append(f"💵 {currency}: ${balance:.2f}")
            else:
                crypto_found = True
                output.append(f"🪙 {currency}: {balance:.8f} ← BLEEDING!")

    output.append("\n" + "="*60)
    if crypto_found:
        output.append("❌ STILL BLEEDING - Crypto holdings remain!")
    else:
        output.append(f"✅ BLEEDING STOPPED - No crypto left!")
        output.append(f"✅ All cash: ${cash_total:.2f}")
    output.append("="*60 + "\n")

except Exception as e:
    output.append(f"ERROR: {e}\n")

# Write to file
with open('/workspaces/Nija/bleeding_status.txt', 'w') as f:
    f.write('\n'.join(output))

# Also print
print('\n'.join(output))
