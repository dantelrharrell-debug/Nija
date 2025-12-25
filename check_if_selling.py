#!/usr/bin/env python3
"""Check if bot is actively trading and selling for profit"""
import os
import sys
import time
from datetime import datetime

sys.path.insert(0, '/usr/src/app/bot')
from coinbase.rest import RESTClient

# Load .env manually
def load_env():
    env_path = '/workspaces/Nija/.env'
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    os.environ[key.strip()] = value.strip().strip('"').strip("'")

load_env()

api_key = os.getenv("COINBASE_API_KEY")
api_secret = os.getenv("COINBASE_API_SECRET", "").replace("\\n", "\n")

client = RESTClient(api_key=api_key, api_secret=api_secret)

print("\n" + "="*70)
print("📊 TRADING ACTIVITY CHECK")
print("="*70)

# Get recent orders
try:
    print("\n🔍 Fetching recent orders (last 50)...\n")
    
    orders_response = client.list_orders(limit=50)
    
    if hasattr(orders_response, 'orders'):
        orders = orders_response.orders
    else:
        orders = getattr(orders_response, 'order', [])
    
    if not orders:
        print("❌ No recent orders found")
        sys.exit(0)
    
    buy_orders = []
    sell_orders = []
    
    for order in orders:
        side = getattr(order, 'side', 'UNKNOWN')
        product = getattr(order, 'product_id', 'UNKNOWN')
        status = getattr(order, 'status', 'UNKNOWN')
        filled_size = float(getattr(order, 'filled_size', 0) or 0)
        filled_value = float(getattr(order, 'filled_value', 0) or 0)
        created_time = getattr(order, 'created_time', 'UNKNOWN')
        
        if side == 'BUY':
            buy_orders.append({
                'product': product,
                'status': status,
                'size': filled_size,
                'value': filled_value,
                'time': created_time
            })
        elif side == 'SELL':
            sell_orders.append({
                'product': product,
                'status': status,
                'size': filled_size,
                'value': filled_value,
                'time': created_time
            })
    
    print(f"📈 BUY ORDERS: {len(buy_orders)}")
    for i, order in enumerate(buy_orders[:10], 1):
        print(f"   {i}. {order['product']}: ${order['value']:.2f} @ {order['time'][:19]}")
    
    print(f"\n📉 SELL ORDERS: {len(sell_orders)}")
    if sell_orders:
        for i, order in enumerate(sell_orders[:10], 1):
            print(f"   {i}. {order['product']}: ${order['value']:.2f} @ {order['time'][:19]}")
    else:
        print("   ❌ NO SELL ORDERS - Bot is NOT selling!")
    
    print("\n" + "="*70)
    
    if len(buy_orders) > 0 and len(sell_orders) == 0:
        print("⚠️  PROBLEM DETECTED:")
        print("   Bot is BUYING but NOT SELLING")
        print("   This means the position closing fix hasn't been deployed yet!")
        print("\n💡 SOLUTION:")
        print("   1. The fix is in your code but not deployed to Railway")
        print("   2. Need to commit and push changes")
        print("   3. Railway will auto-deploy the fixed code")
    elif len(sell_orders) > 0:
        print("✅ Bot IS selling positions!")
        sell_ratio = len(sell_orders) / len(buy_orders) if buy_orders else 0
        print(f"   Sell/Buy ratio: {sell_ratio:.2%}")
    
    print("="*70 + "\n")
    
except Exception as e:
    print(f"❌ Error checking orders: {e}")
