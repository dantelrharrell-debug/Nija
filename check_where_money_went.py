#!/usr/bin/env python3
"""
Check where funds are located across Coinbase accounts
Run this to see if your $84 sale proceeds are visible
"""

import os
from dotenv import load_dotenv
from coinbase.rest import RESTClient

load_dotenv()

api_key = os.getenv("COINBASE_API_KEY")
api_secret = os.getenv("COINBASE_API_SECRET")

if not api_key or not api_secret:
    print("❌ Missing API credentials")
    exit(1)

# Normalize escaped newlines
api_secret = api_secret.replace("\\n", "\n")

client = RESTClient(api_key=api_key, api_secret=api_secret)

print("\n🔍 CHECKING ALL COINBASE ACCOUNTS")
print("=" * 60)

try:
    accounts_response = client.get_accounts()
    # SDK returns object with .accounts attribute, not dict
    accounts = accounts_response.accounts if hasattr(accounts_response, 'accounts') else []
    
    print(f"\n✅ Found {len(accounts)} total accounts\n")
    
    usd_accounts = []
    usdc_accounts = []
    crypto_accounts = []
    
    for acc in accounts:
        currency = acc.get("currency", "")
        balance = float(acc.get("available_balance", {}).get("value", 0))
        acc_type = acc.get("type", "UNKNOWN")
        name = acc.get("name", "")
        uuid = acc.get("uuid", "")
        
        if balance > 0:
            if currency == "USD":
                usd_accounts.append({
                    'name': name,
                    'type': acc_type,
                    'balance': balance,
                    'uuid': uuid
                })
            elif currency == "USDC":
                usdc_accounts.append({
                    'name': name,
                    'type': acc_type,
                    'balance': balance,
                    'uuid': uuid
                })
            else:
                crypto_accounts.append({
                    'currency': currency,
                    'name': name,
                    'type': acc_type,
                    'balance': balance,
                    'uuid': uuid
                })
    
    # Print USD accounts
    if usd_accounts:
        print("💵 USD ACCOUNTS WITH BALANCE:")
        for acc in usd_accounts:
            print(f"   {acc['name']}")
            print(f"      Type: {acc['type']}")
            print(f"      Balance: ${acc['balance']:.2f}")
            print(f"      UUID: {acc['uuid'][:8]}...")
            print()
    else:
        print("💵 USD ACCOUNTS: None with balance\n")
    
    # Print USDC accounts
    if usdc_accounts:
        print("💰 USDC ACCOUNTS WITH BALANCE:")
        for acc in usdc_accounts:
            print(f"   {acc['name']}")
            print(f"      Type: {acc['type']}")
            print(f"      Balance: ${acc['balance']:.2f}")
            print(f"      UUID: {acc['uuid'][:8]}...")
            print()
    else:
        print("💰 USDC ACCOUNTS: None with balance\n")
    
    # Print crypto accounts
    if crypto_accounts:
        print("🪙 CRYPTO ACCOUNTS WITH BALANCE:")
        for acc in crypto_accounts:
            print(f"   {acc['currency']}")
            print(f"      Name: {acc['name']}")
            print(f"      Type: {acc['type']}")
            print(f"      Balance: {acc['balance']:.8f}")
            print(f"      UUID: {acc['uuid'][:8]}...")
            print()
    else:
        print("🪙 CRYPTO ACCOUNTS: None with balance\n")
    
    # Calculate totals
    total_usd = sum(acc['balance'] for acc in usd_accounts)
    total_usdc = sum(acc['balance'] for acc in usdc_accounts)
    
    print("=" * 60)
    print(f"📊 SUMMARY:")
    print(f"   Total USD:  ${total_usd:.2f}")
    print(f"   Total USDC: ${total_usdc:.2f}")
    print(f"   Crypto assets: {len(crypto_accounts)} different coins")
    print("=" * 60)
    
    if total_usd == 0 and total_usdc == 0:
        print("\n⚠️  NO USD/USDC FOUND")
        print("\n🔍 Possible reasons:")
        print("   1. Funds still settling from recent sale")
        print("   2. API keys point to different account than web UI")
        print("   3. Funds in external/Consumer wallet (not Advanced Trade)")
        print("\n💡 Check Coinbase web app to see where your $84 went:")
        print("   https://www.coinbase.com/settings/portfolio")

except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
