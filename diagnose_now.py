#!/usr/bin/env python3
"""
Quick diagnostic: Check where your money actually is
"""
import os
import sys
from dotenv import load_dotenv
load_dotenv()

sys.path.insert(0, 'bot')
from coinbase.rest import RESTClient

print("\n" + "="*80)
print("🔍 NIJA MONEY DIAGNOSTIC - WHERE IS YOUR MONEY?")
print("="*80)

try:
    client = RESTClient(
        api_key=os.getenv('COINBASE_API_KEY'), 
        api_secret=os.getenv('COINBASE_API_SECRET')
    )
    
    # 1. Check all accounts
    print("\n📊 ALL ACCOUNT BALANCES:")
    print("-" * 80)
    accounts_resp = client.get_accounts()
    accounts = getattr(accounts_resp, 'accounts', [])
    
    total_usd = 0
    total_crypto = 0
    consumer_usd = 0
    crypto_details = {}
    
    for acc in accounts:
        curr = getattr(acc, 'currency', None)
        avail = float(getattr(getattr(acc, 'available_balance', {}), 'value', 0) or 0)
        acc_type = getattr(acc, 'type', 'UNKNOWN')
        
        if avail <= 0:
            continue
            
        if curr in ['USD', 'USDC']:
            print(f"   {curr:6s}: ${avail:10.2f}  ({acc_type})")
            if 'CONSUMER' in acc_type.upper() or 'WALLET' in acc_type.upper():
                consumer_usd += avail
            else:
                total_usd += avail
        elif curr:
            crypto_details[curr] = avail
            print(f"   {curr:6s}: {avail:10.8f}  ({acc_type})")
            total_crypto += 1
    
    # 2. Check crypto values
    print("\n💎 CRYPTO HOLDINGS (VALUE IN USD):")
    print("-" * 80)
    total_crypto_value = 0
    for crypto_sym, bal in crypto_details.items():
        try:
            prod = client.get_product(f"{crypto_sym}-USD")
            price = float(getattr(prod, 'price', 0) or 0)
            value = bal * price
            total_crypto_value += value
            print(f"   {crypto_sym:6s}: {bal:8.4f} @ ${price:8.2f} = ${value:10.2f}")
        except:
            print(f"   {crypto_sym:6s}: {bal:8.4f} @ $?.?? = $??.??")
    
    # 3. Summary
    print("\n" + "="*80)
    print("💰 SUMMARY:")
    print("="*80)
    print(f"   Advanced Trade USD/USDC: ${total_usd:10.2f} ✅ TRADABLE")
    print(f"   Consumer Wallet:         ${consumer_usd:10.2f} ❌ NOT TRADABLE")
    print(f"   Crypto Holdings (Value): ${total_crypto_value:10.2f}")
    print(f"   TOTAL PORTFOLIO:         ${total_usd + consumer_usd + total_crypto_value:10.2f}")
    
    print("\n" + "="*80)
    print("🎯 NEXT STEPS:")
    print("="*80)
    
    if total_usd >= 5.0:
        print(f"✅ You have ${total_usd:.2f} in Advanced Trade - BOT CAN START TRADING!")
        print("\n   Action: Restart the bot - it should now trade")
    elif consumer_usd > 0:
        print(f"⚠️  You have ${consumer_usd:.2f} in Consumer wallet")
        print(f"❌ Bot needs funds in Advanced Trade portfolio")
        print("\n   Action: Transfer to Advanced Trade")
        print(f"   https://www.coinbase.com/advanced-portfolio")
        print(f"   → Deposit ${consumer_usd:.2f} from Consumer wallet")
    elif total_crypto_value > 0:
        print(f"💎 You have ${total_crypto_value:.2f} in crypto")
        print(f"❌ Bot needs USD/USDC, not crypto")
        print("\n   Action: Sell crypto for USD on Coinbase")
        print(f"   → Convert to USD")
        print(f"   → Transfer USD to Advanced Trade")
    else:
        print(f"❌ Your account appears empty")
        print("\n   Action: Deposit funds to get started")
    
    print("="*80 + "\n")
    
except Exception as e:
    print(f"\n❌ ERROR: {e}\n")
    import traceback
    traceback.print_exc()
