#!/usr/bin/env python3
"""Debug - show ALL accounts to see what's being returned"""
import os
import sys
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, '/workspaces/Nija')

from bot.broker_manager import CoinbaseBroker

broker = CoinbaseBroker()
if not broker.connect():
    print("❌ Connection failed")
    sys.exit(1)

print("\n" + "="*80)
print("🔍 DEBUG: ALL COINBASE ACCOUNTS")
print("="*80 + "\n")

accounts_response = broker.client.get_accounts()

if hasattr(accounts_response, 'accounts'):
    all_accounts = accounts_response.accounts
else:
    all_accounts = accounts_response.get('accounts', [])

print(f"Total accounts found: {len(all_accounts)}\n")

for i, account in enumerate(all_accounts, 1):
    print(f"Account #{i}:")
    if hasattr(account, 'currency'):
        currency = account.currency
        name = getattr(account, 'name', 'N/A')
        acc_type = getattr(account, 'type', 'N/A')
        available_bal = account.available_balance
        if hasattr(available_bal, 'value'):
            available = float(available_bal.value)
        elif isinstance(available_bal, dict):
            available = float(available_bal.get('value', 0))
        else:
            try:
                available = float(str(available_bal))
            except:
                available = 0
        
        print(f"  Currency: {currency}")
        print(f"  Name: {name}")
        print(f"  Type: {acc_type}")
        print(f"  Available: {available}")
        
        # Show if it has crypto holdings
        if currency not in ['USD', 'USDC'] and available > 0.00000001:
            print(f"  ⚠️  HAS CRYPTO: {available}")
    else:
        print(f"  Raw: {account}")
    print()

print("="*80)
