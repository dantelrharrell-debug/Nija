#!/usr/bin/env python3
"""
DIRECT SELL - Based on exact data from deep_diagnostic
"""
import os
import sys
import time
from uuid import uuid4
from dotenv import load_dotenv
load_dotenv()

sys.path.append('/workspaces/Nija/bot')
from coinbase.rest import RESTClient

client = RESTClient(
    api_key=os.getenv("COINBASE_API_KEY"),
    api_secret=os.getenv("COINBASE_API_SECRET")
)

# These are the EXACT positions from deep_diagnostic.py
crypto_positions = [
    {'currency': 'IMX', 'balance': 4.98},
    {'currency': 'LRC', 'balance': 18.642739},
    {'currency': 'APT', 'balance': 3.747},
    {'currency': 'SHIB', 'balance': 151016},
    {'currency': 'VET', 'balance': 105},
    {'currency': 'BAT', 'balance': 10.21},
    {'currency': 'XLM', 'balance': 5.1928634},
    {'currency': 'AVAX', 'balance': 0.40064619},
    {'currency': 'ADA', 'balance': 32.33642619},
]

print("\n" + "="*80)
print("💸 DIRECT CRYPTO SELL")
print("="*80)
print(f"\nFound {len(crypto_positions)} positions:\n")

for p in crypto_positions:
    print(f"   • {p['currency']}: {p['balance']}")

confirm = input("\n🔥 SELL ALL? Type 'YES' to proceed: ")

if confirm.strip().upper() != "YES":
    print("\n❌ Cancelled")
    sys.exit(0)

print("\n" + "="*80)
print("💸 SELLING...")
print("="*80)

sold = 0
failed = 0

for crypto in crypto_positions:
    currency = crypto['currency']
    balance = crypto['balance']
    product_id = f"{currency}-USD"
    
    print(f"\n📤 Selling {balance} {currency}...", end=" ")
    
    try:
        base_size = round(balance, 8)
        
        order = client.market_order_sell(
            client_order_id=str(uuid4()),
            product_id=product_id,
            base_size=str(base_size)
        )
        
        # Safely serialize Coinbase SDK response objects
        if isinstance(order, dict):
            order_dict = order
        else:
            # Convert object to dict safely
            try:
                import json
                json_str = json.dumps(order, default=str)
                order_dict = json.loads(json_str)
            except Exception:
                # Fallback: just try __dict__
                order_dict = {}
                if hasattr(order, '__dict__'):
                    for k, v in order.__dict__.items():
                        if isinstance(v, (dict, list, str, int, float, bool, type(None))):
                            order_dict[k] = v
                        else:
                            order_dict[k] = str(v)
        
        success = order_dict.get('success', True)
        error = order_dict.get('error_response', {})
        
        if success and not error:
            sold += 1
            print("✅ SOLD")
        else:
            failed += 1
            msg = error.get('message', 'Unknown error')
            print(f"❌ {msg}")
    
    except Exception as e:
        failed += 1
        print(f"❌ {str(e)}")
    
    time.sleep(0.5)

print("\n" + "="*80)
print(f"Results: {sold} sold, {failed} failed")
print("="*80)

if sold > 0:
    print("\n⏳ Waiting 5 seconds...")
    time.sleep(5)
    
    print("\n🔄 Checking balance...")
    accounts_resp = client.get_accounts()
    accounts = getattr(accounts_resp, 'accounts', [])
    
    usd_total = 0
    usdc_total = 0
    
    for account in accounts:
        currency = getattr(account, 'currency', None)
        available = getattr(account, 'available_balance', None)
        
        if not currency or not available:
            continue
        
        balance = float(getattr(available, 'value', '0'))
        
        if currency == 'USD':
            usd_total += balance
        elif currency == 'USDC':
            usdc_total += balance
    
    total_cash = usd_total + usdc_total
    
    print(f"\n💰 NEW BALANCE:")
    print(f"   USD:  ${usd_total:.2f}")
    print(f"   USDC: ${usdc_total:.2f}")
    print(f"   TOTAL: ${total_cash:.2f}")
    
    if total_cash >= 10:
        print(f"\n✅ You now have ${total_cash:.2f}!")
        print("   Transfer to Advanced Trade to enable bot trading")
    else:
        print("\n⚠️  Still need more funds for trading")

print("\n" + "="*80)
