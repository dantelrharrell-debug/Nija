#!/usr/bin/env python3
"""Check if bot started selling after deployment"""
import os
import sys
from datetime import datetime, timedelta
sys.path.insert(0, '/usr/src/app/bot')
from coinbase.rest import RESTClient

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
print("🔍 CHECKING IF BOT IS SELLING NOW")
print("="*70)

orders_response = client.list_orders(limit=100)
if hasattr(orders_response, 'orders'):
    orders = orders_response.orders
else:
    orders = getattr(orders_response, 'order', [])

# Separate by timeframe
cutoff_time = datetime.now() - timedelta(minutes=10)
recent_buys = []
recent_sells = []
all_buys = 0
all_sells = 0

for order in orders:
    side = getattr(order, 'side', 'UNKNOWN')
    product = getattr(order, 'product_id', 'UNKNOWN')
    filled_value = float(getattr(order, 'filled_value', 0) or 0)
    created_time_str = getattr(order, 'created_time', 'UNKNOWN')
    
    try:
        created_time = datetime.fromisoformat(created_time_str.replace('Z', '+00:00'))
        is_recent = created_time.replace(tzinfo=None) > cutoff_time
    except:
        is_recent = False
    
    if side == 'BUY':
        all_buys += 1
        if is_recent:
            recent_buys.append({
                'product': product,
                'value': filled_value,
                'time': created_time_str[:19]
            })
    elif side == 'SELL':
        all_sells += 1
        if is_recent:
            recent_sells.append({
                'product': product,
                'value': filled_value,
                'time': created_time_str[:19]
            })

print(f"\n📊 LAST 10 MINUTES:")
print(f"   BUYs:  {len(recent_buys)}")
print(f"   SELLs: {len(recent_sells)}")

if recent_sells:
    print(f"\n🎉 NEW SELLS DETECTED!")
    for sell in recent_sells[:5]:
        print(f"   ✅ {sell['product']}: ${sell['value']:.2f} @ {sell['time']}")
else:
    print(f"   ⏳ No new sells in last 10 minutes")

print(f"\n📊 ALL TIME (last 100 orders):")
print(f"   Total BUYs:  {all_buys}")
print(f"   Total SELLs: {all_sells}")

sell_ratio = (all_sells / all_buys * 100) if all_buys > 0 else 0
print(f"   Sell Ratio:  {sell_ratio:.1f}%")

if sell_ratio > 50:
    print(f"   Status: ✅ EXCELLENT - Healthy selling")
elif sell_ratio > 30:
    print(f"   Status: ✅ GOOD - Fix is working!")
elif sell_ratio > 15:
    print(f"   Status: ⚠️  IMPROVING - Give it more time")
else:
    print(f"   Status: ❌ NOT YET - Deployment may not be live")

# Check most recent activity
print(f"\n📋 MOST RECENT ORDERS:")
recent_orders = []
for order in orders[:10]:
    side = getattr(order, 'side', 'UNKNOWN')
    product = getattr(order, 'product_id', 'UNKNOWN')
    filled_value = float(getattr(order, 'filled_value', 0) or 0)
    created_time = getattr(order, 'created_time', 'UNKNOWN')[:19]
    
    emoji = "📈" if side == "BUY" else "📉"
    recent_orders.append(f"   {emoji} {side:4} {product:10} ${filled_value:7.2f} @ {created_time}")

for order_str in recent_orders:
    print(order_str)

print("\n" + "="*70)

if recent_sells:
    print("✅ BOT IS SELLING! Fix deployed successfully!")
elif len(recent_buys) > 0:
    print("⚠️  Bot is buying but not selling yet")
    print("   - Deployment may still be in progress")
    print("   - Or positions haven't hit profit targets yet")
    print("   - Check again in 5 minutes")
else:
    print("ℹ️  No recent activity in last 10 minutes")
    
print("="*70 + "\n")
