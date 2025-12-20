#!/usr/bin/env python3
"""
FINAL LIQUIDATION: Sell all crypto holdings to USD
Consolidates everything to Advanced Trade USD balance
"""

import sys
import os
from datetime import datetime
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

from dotenv import load_dotenv
from coinbase.rest import RESTClient

load_dotenv()

print("=" * 80)
print("🚨 FINAL LIQUIDATION - SELL ALL CRYPTO TO USD")
print("=" * 80)
print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print()

# Connect to Coinbase
try:
    client = RESTClient(
        api_key=os.getenv('COINBASE_API_KEY'),
        api_secret=os.getenv('COINBASE_API_SECRET')
    )
    print("✅ Connected to Coinbase API")
except Exception as e:
    print(f"❌ Failed to connect: {e}")
    sys.exit(1)

print()
print("=" * 80)
print("STEP 1: SCAN ALL ACCOUNTS")
print("=" * 80)
print()

# Get all accounts/balances
try:
    accounts_resp = client.get_accounts()
    accounts = getattr(accounts_resp, 'accounts', [])
    
    print(f"Found {len(accounts)} accounts\n")
    
    crypto_holdings = []
    usd_balance = 0.0
    
    for acc in accounts:
        currency = getattr(acc, 'currency', None)
        avail = getattr(acc, 'available_balance', None)
        hold = getattr(acc, 'hold', None)
        
        if not currency or not avail:
            continue
        
        avail_val = float(getattr(avail, 'value', 0))
        hold_val = float(getattr(hold, 'value', 0)) if hold else 0
        
        if avail_val > 0.001 or hold_val > 0.001:
            print(f"{currency:8s}: Available: {avail_val:12.8f}  Hold: {hold_val:12.8f}")
            
            if currency in ['USD', 'USDC']:
                usd_balance += avail_val
            else:
                crypto_holdings.append({
                    'currency': currency,
                    'amount': avail_val,
                    'hold': hold_val
                })
    
    print()
    print(f"📊 Summary:")
    print(f"   USD/USDC Balance: ${usd_balance:.2f}")
    print(f"   Crypto Holdings: {len(crypto_holdings)} different coins")
    
except Exception as e:
    print(f"❌ Error fetching accounts: {e}")
    sys.exit(1)

if not crypto_holdings:
    print()
    print("✅ No crypto holdings to sell!")
    print(f"   Final USD Balance: ${usd_balance:.2f}")
    sys.exit(0)

print()
print("=" * 80)
print("STEP 2: SELL ALL CRYPTO")
print("=" * 80)
print()

successful_sales = 0
failed_sales = 0

for holding in crypto_holdings:
    currency = holding['currency']
    amount = holding['amount']
    
    if amount < 0.0001:
        print(f"⏭️  {currency:8s}: Skipping (dust amount: {amount:.8f})")
        continue
    
    symbol = f"{currency}-USD"
    
    print(f"🔄 Selling {amount:.8f} {currency} as {symbol}...")
    
    try:
        # Sell at market price
        order = client.market_order_sell(
            product_id=symbol,
            base_size=str(amount)
        )
        
        order_id = getattr(order, 'id', 'unknown')
        status = getattr(order, 'status', 'unknown')
        
        print(f"   ✅ Order {order_id}: {status}")
        print(f"      Sold: {amount:.8f} {currency}")
        
        successful_sales += 1
        time.sleep(1)  # Rate limit protection
        
    except Exception as e:
        print(f"   ❌ Failed: {str(e)[:100]}")
        failed_sales += 1
        time.sleep(1)

print()
print("=" * 80)
print("STEP 3: CHECK FINAL BALANCE")
print("=" * 80)
print()

time.sleep(2)  # Wait for orders to settle

try:
    accounts_resp = client.get_accounts()
    accounts = getattr(accounts_resp, 'accounts', [])
    
    final_usd = 0.0
    remaining_crypto = []
    
    for acc in accounts:
        currency = getattr(acc, 'currency', None)
        avail = getattr(acc, 'available_balance', None)
        
        if not currency or not avail:
            continue
        
        avail_val = float(getattr(avail, 'value', 0))
        
        if avail_val > 0.001:
            if currency in ['USD', 'USDC']:
                final_usd += avail_val
                print(f"💰 {currency:8s}: ${avail_val:.2f}")
            else:
                remaining_crypto.append({
                    'currency': currency,
                    'amount': avail_val
                })
                print(f"⚠️  {currency:8s}: {avail_val:.8f} (not sold yet)")
    
    print()
    print("=" * 80)
    print("📊 FINAL SUMMARY")
    print("=" * 80)
    print()
    print(f"✅ Successful Sales: {successful_sales}")
    print(f"❌ Failed Sales: {failed_sales}")
    print()
    print(f"💰 Final USD Balance: ${final_usd:.2f}")
    print(f"📦 Remaining Crypto: {len(remaining_crypto)}")
    
    if remaining_crypto:
        print()
        print("   Still holding:")
        for r in remaining_crypto:
            print(f"     - {r['currency']}: {r['amount']:.8f}")
    
    print()
    print("=" * 80)
    
    if failed_sales > 0:
        print(f"⚠️  {failed_sales} sales failed. Will retry...")
        print()
    else:
        print("✅ ALL CRYPTO LIQUIDATED TO USD")
        print()
    
except Exception as e:
    print(f"❌ Error checking final balance: {e}")

print("Done.")
