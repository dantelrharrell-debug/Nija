#!/usr/bin/env python3
"""Quick deployment verification"""
import os
import sys
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
print("📊 DEPLOYMENT VERIFICATION")
print("="*70)

orders_response = client.list_orders(limit=50)
if hasattr(orders_response, 'orders'):
    orders = orders_response.orders
else:
    orders = getattr(orders_response, 'order', [])

buy_count = sum(1 for o in orders if getattr(o, 'side', '') == 'BUY')
sell_count = sum(1 for o in orders if getattr(o, 'side', '') == 'SELL')
sell_ratio = (sell_count / buy_count * 100) if buy_count > 0 else 0

print(f"\n📈 BUY orders:  {buy_count}")
print(f"📉 SELL orders: {sell_count}")
print(f"📊 Sell ratio:  {sell_ratio:.1f}%")

if sell_ratio < 30:
    print("\n⏳ Railway is still deploying...")
    print("   Wait 2-3 minutes and run: python3 verify_deployment.py")
else:
    print("\n✅ Bot is selling!")

print("="*70 + "\n")
