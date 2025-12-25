#!/usr/bin/env python3
"""
EMERGENCY LIQUIDATE - Sell ALL crypto immediately regardless of loss
This FORCES an exit to stop further bleeding
"""
import os
import sys
import time
import json
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))
from coinbase.rest import RESTClient

print("\n" + "="*80)
print("🚨 EMERGENCY LIQUIDATION - SELL ALL CRYPTO NOW")
print("="*80)
print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("\n⚠️  WARNING: This will SELL ALL cryptocurrency at market price")
print("   You WILL take losses if underwater")
print("   But you STOP further losses\n")

# Confirm
resp = input("Type 'YES I UNDERSTAND' to proceed: ")
if resp != 'YES I UNDERSTAND':
    print("\n❌ Cancelled. No trades made.")
    sys.exit(0)

print("\n" + "="*80)
print("Proceeding with liquidation...")
print("="*80 + "\n")

# Initialize client
client = RESTClient(
    api_key=os.getenv('COINBASE_API_KEY'),
    api_secret=os.getenv('COINBASE_API_SECRET')
)

# Get all accounts
print("📊 Fetching all holdings...")
accounts_resp = client.get_accounts()
accounts = getattr(accounts_resp, 'accounts', [])

crypto_to_sell = []
cash_balance = 0
cash_currency = 'USD'

for acc in accounts:
    curr = getattr(acc, 'currency', None)
    avail = getattr(acc, 'available_balance', None)
    
    if not curr or not avail:
        continue
    
    bal = float(getattr(avail, 'value', '0'))
    
    if bal <= 0:
        continue
    
    if curr in ['USD', 'USDC']:
        cash_balance += bal
        if curr == 'USDC':
            cash_currency = 'USDC'
    else:
        crypto_to_sell.append({
            'currency': curr,
            'balance': bal,
            'symbol': f"{curr}-USD"
        })

print(f"\n💵 Cash available: ${cash_balance:.2f} ({cash_currency})")
print(f"🪙 Crypto positions to liquidate: {len(crypto_to_sell)}\n")

if not crypto_to_sell:
    print("✅ No crypto to sell. Account is already all-cash.")
    sys.exit(0)

# Get current prices for all positions
print("📈 Fetching current prices...")
total_current_value = 0

for pos in crypto_to_sell:
    try:
        product = client.get_product(pos['symbol'])
        price = float(getattr(product, 'price', 0))
        value = pos['balance'] * price
        total_current_value += value
        pos['price'] = price
        pos['value'] = value
        print(f"   {pos['currency']:8s} {pos['balance']:15.8f} @ ${price:10.2f} = ${value:10.2f}")
    except Exception as e:
        print(f"   {pos['currency']:8s} {pos['balance']:15.8f} @ ERROR (will try anyway)")
        pos['price'] = 0
        pos['value'] = 0

print(f"\n💎 Total crypto value: ${total_current_value:.2f}")
print(f"📊 New portfolio after sale: ${cash_balance + total_current_value:.2f} (all cash)")

print("\n" + "="*80)
print("EXECUTING LIQUIDATION...")
print("="*80 + "\n")

successful_sales = 0
failed_sales = 0
total_proceeds = 0

for i, pos in enumerate(crypto_to_sell, 1):
    curr = pos['currency']
    symbol = pos['symbol']
    qty = pos['balance']
    price = pos['price']
    
    try:
        print(f"\n{i}. Selling {curr}...")
        print(f"   Quantity: {qty:.8f}")
        print(f"   Price: ${price:.2f}")
        
        # Place market sell order
        order_result = client.market_order_sell(
            client_order_id=f"emergency_sell_{curr}_{int(time.time())}",
            product_id=symbol,
            quote_size=pos['value']  # Sell by USD value
        )
        
        # Check if order succeeded
        order_id = getattr(order_result, 'order_id', None)
        status = getattr(order_result, 'status', 'unknown')
        
        if order_id:
            print(f"   ✅ Order placed: {order_id}")
            print(f"   Status: {status}")
            successful_sales += 1
            total_proceeds += pos['value']
            
            # Wait a bit between orders to avoid rate limiting
            time.sleep(1)
        else:
            print(f"   ❌ Failed to place order")
            failed_sales += 1
    
    except Exception as e:
        print(f"   ❌ Error selling {curr}: {e}")
        failed_sales += 1

print("\n" + "="*80)
print("LIQUIDATION COMPLETE")
print("="*80)

print(f"\n✅ Successful sales: {successful_sales}")
print(f"❌ Failed sales: {failed_sales}")
print(f"💰 Proceeds: ${total_proceeds:.2f}")

if failed_sales > 0:
    print(f"\n⚠️  {failed_sales} positions failed to sell")
    print("   Possible reasons:")
    print("   • Insufficient liquidity for the pair")
    print("   • API rate limiting")
    print("   • Network issues")
    print("\n   ACTION: Check Coinbase web interface and sell manually")

print("\n" + "="*80)
print("💡 NEXT STEPS:")
print("="*80)
print("\n1. Verify all sales completed in Coinbase web interface")
print("2. Check that all crypto is gone and you're 100% cash")
print("3. Review trade journal to understand what went wrong")
print("4. Disable NIJA until we fix the exit/sell logic")
print("5. When restarting: Clear position files to reset bot state")

print("\n" + "="*80 + "\n")
