#!/usr/bin/env python3
"""
Check Advanced Trade portfolio balances with proper account filtering
"""
import os
import sys
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))
from coinbase.rest import RESTClient

client = RESTClient(
    api_key=os.getenv('COINBASE_API_KEY'),
    api_secret=os.getenv('COINBASE_API_SECRET')
)

print("\n" + "="*80)
print("💼 ADVANCED TRADE PORTFOLIO CHECK")
print("="*80 + "\n")

# Get all accounts
accounts_resp = client.get_accounts()
accounts = getattr(accounts_resp, 'accounts', [])

print(f"Total accounts: {len(accounts)}\n")

# Filter only ADVANCED TRADE accounts
advanced_trade = []
consumer = []
crypto_positions = []

for acc in accounts:
    platform = getattr(acc, 'platform', 'UNKNOWN')
    curr = getattr(acc, 'currency', None)
    avail_obj = getattr(acc, 'available_balance', None)
    hold_obj = getattr(acc, 'hold', None)
    
    if not curr:
        continue
    
    avail_bal = float(getattr(avail_obj, 'value', '0')) if avail_obj else 0
    hold_bal = float(getattr(hold_obj, 'value', '0')) if hold_obj else 0
    total_bal = avail_bal + hold_bal
    
    if platform == 'ACCOUNT_PLATFORM_ADVANCED_TRADE':
        advanced_trade.append({
            'currency': curr,
            'available': avail_bal,
            'hold': hold_bal,
            'total': total_bal
        })
    elif platform == 'ACCOUNT_PLATFORM_CONSUMER':
        consumer.append({
            'currency': curr,
            'available': avail_bal,
            'hold': hold_bal,
            'total': total_bal
        })
    
    # Show any position with balance (available or hold)
    if total_bal > 0:
        crypto_positions.append({
            'currency': curr,
            'available': avail_bal,
            'hold': hold_bal,
            'total': total_bal,
            'platform': platform
        })

print("="*80)
print("📍 ADVANCED TRADE ACCOUNTS")
print("="*80)
if advanced_trade:
    for acc in advanced_trade:
        if acc['total'] > 0:
            print(f"{acc['currency']:8s}: {acc['total']:15.8f} (Available: {acc['available']}, Hold: {acc['hold']})")
else:
    print("No Advanced Trade accounts")

print("\n" + "="*80)
print("🏦 CONSUMER ACCOUNTS")
print("="*80)
if consumer:
    for acc in consumer:
        if acc['total'] > 0:
            print(f"{acc['currency']:8s}: {acc['total']:15.8f} (Available: {acc['available']}, Hold: {acc['hold']})")
else:
    print("No Consumer accounts with balance")

print("\n" + "="*80)
print("💰 ALL CRYPTO POSITIONS (ANY PLATFORM)")
print("="*80)
if crypto_positions:
    print(f"\nFound {len(crypto_positions)} positions:\n")
    total_value = 0
    for pos in crypto_positions:
        print(f"{pos['currency']:8s}: {pos['total']:15.8f} ({pos['platform']})")
else:
    print("No crypto positions found")

print("\n" + "="*80 + "\n")
