#!/usr/bin/env python3
"""
Deep dive into order history - get FULL details of each order
"""

import sys
import os
from datetime import datetime
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

from coinbase.rest import RESTClient
from dotenv import load_dotenv

load_dotenv()

print("=" * 80)
print("🔬 DEEP ORDER ANALYSIS - CHECKING IF BUYS ACTUALLY FILLED")
print("=" * 80)
print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

client = RESTClient(
    api_key=os.getenv('COINBASE_API_KEY'),
    api_secret=os.getenv('COINBASE_API_SECRET')
)

# Get recent orders
print("📋 Fetching last 50 orders with FULL details...\n")

orders = client.list_orders(limit=50)
order_list = getattr(orders, 'orders', [])

buy_orders = []
sell_orders = []

for order in order_list:
    side = getattr(order, 'side', 'N/A')
    
    if side == 'BUY':
        buy_orders.append(order)
    elif side == 'SELL':
        sell_orders.append(order)

print(f"✅ Found {len(buy_orders)} BUY orders, {len(sell_orders)} SELL orders\n")

# Analyze BUY orders in detail
print("=" * 80)
print("📊 ANALYZING BUY ORDERS (Last 10)")
print("=" * 80)

total_spent = 0
total_received_crypto = 0
failed_orders = 0

for i, order in enumerate(buy_orders[:10], 1):
    product_id = getattr(order, 'product_id', 'N/A')
    status = getattr(order, 'status', 'N/A')
    created = getattr(order, 'created_time', 'N/A')
    order_id = getattr(order, 'order_id', 'N/A')
    
    # Get filled details
    filled_size_obj = getattr(order, 'filled_size', None)
    filled_value_obj = getattr(order, 'total_value_after_fees', None)
    
    if filled_size_obj:
        filled_size = float(getattr(filled_size_obj, 'value', 0))
    else:
        filled_size = 0
    
    if filled_value_obj:
        filled_value = float(getattr(filled_value_obj, 'value', 0))
    else:
        filled_value = 0
    
    # Get average filled price
    avg_price_obj = getattr(order, 'average_filled_price', None)
    if avg_price_obj:
        avg_price = float(getattr(avg_price_obj, 'value', 0))
    else:
        avg_price = 0
    
    # Rejection reason if any
    reject_reason = getattr(order, 'reject_reason', None)
    cancel_reason = getattr(order, 'cancel_reason', None)
    
    print(f"\n{i}. {product_id} - {status}")
    print(f"   Order ID: {order_id}")
    print(f"   Created: {created}")
    print(f"   Filled Size: {filled_size:.8f}")
    print(f"   Filled Value: ${filled_value:.2f}")
    print(f"   Avg Price: ${avg_price:.4f}")
    
    if reject_reason:
        print(f"   ❌ REJECTED: {reject_reason}")
        failed_orders += 1
    elif cancel_reason:
        print(f"   ❌ CANCELLED: {cancel_reason}")
        failed_orders += 1
    elif status != 'FILLED':
        print(f"   ⚠️  NOT FILLED (Status: {status})")
        failed_orders += 1
    elif filled_value == 0:
        print(f"   ⚠️  FILLED BUT $0 VALUE - API DATA ISSUE")
        failed_orders += 1
    else:
        print(f"   ✅ SUCCESS")
        total_spent += filled_value
        total_received_crypto += 1

print("\n" + "=" * 80)
print("📊 BUY ORDER SUMMARY")
print("=" * 80)
print(f"Total BUY orders checked: {min(10, len(buy_orders))}")
print(f"Successfully filled: {total_received_crypto}")
print(f"Failed/Rejected: {failed_orders}")
print(f"Total USD spent: ${total_spent:.2f}")

# Now check where that crypto went
if total_received_crypto > 0 and total_spent > 0:
    print("\n" + "=" * 80)
    print("🔍 MYSTERY: YOU BOUGHT CRYPTO BUT IT'S GONE")
    print("=" * 80)
    print(f"\n✅ You spent ${total_spent:.2f} on {total_received_crypto} positions")
    print(f"❌ Current crypto balance: $0.00")
    print(f"❌ Current USD balance: $0.00")
    print("\n🎯 POSSIBLE EXPLANATIONS:")
    print("   1. Crypto was manually sold on Coinbase.com")
    print("   2. Crypto was sent/transferred to external wallet")
    print("   3. Coinbase liquidated positions (margin call, violation)")
    print("   4. Account was compromised (unauthorized withdrawal)")
    print("\n📱 CHECK YOUR COINBASE ACCOUNT:")
    print("   https://www.coinbase.com/transactions")
    print("   Look for SELL orders or SEND transactions")

elif failed_orders == min(10, len(buy_orders)):
    print("\n" + "=" * 80)
    print("✅ GOOD NEWS: ORDERS NEVER ACTUALLY FILLED")
    print("=" * 80)
    print("\nAll BUY orders were rejected/failed!")
    print("This means you never actually spent money.")
    print("The $95 you started with should still be there.")
    print("\nPossible location: Consumer wallet as USDC")

print("\n" + "=" * 80)
