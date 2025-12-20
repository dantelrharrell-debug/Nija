#!/usr/bin/env python3
"""Monitor bot's selling activity after deployment"""
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
print("🔍 MONITORING BOT SELLING ACTIVITY")
print("="*70)
print("\nChecking every 30 seconds for new SELL orders...")
print("Press Ctrl+C to stop\n")

last_sell_count = 0
last_buy_count = 0

try:
    while True:
        try:
            # Get recent orders
            orders_response = client.list_orders(limit=50)
            
            if hasattr(orders_response, 'orders'):
                orders = orders_response.orders
            else:
                orders = getattr(orders_response, 'order', [])
            
            buy_count = 0
            sell_count = 0
            recent_sells = []
            recent_buys = []
            
            for order in orders:
                side = getattr(order, 'side', 'UNKNOWN')
                product = getattr(order, 'product_id', 'UNKNOWN')
                filled_value = float(getattr(order, 'filled_value', 0) or 0)
                created_time = getattr(order, 'created_time', 'UNKNOWN')
                
                if side == 'BUY':
                    buy_count += 1
                    if buy_count <= 5:
                        recent_buys.append({
                            'product': product,
                            'value': filled_value,
                            'time': created_time[:19] if created_time != 'UNKNOWN' else 'UNKNOWN'
                        })
                elif side == 'SELL':
                    sell_count += 1
                    if sell_count <= 5:
                        recent_sells.append({
                            'product': product,
                            'value': filled_value,
                            'time': created_time[:19] if created_time != 'UNKNOWN' else 'UNKNOWN'
                        })
            
            # Check for new activity
            new_sells = sell_count - last_sell_count
            new_buys = buy_count - last_buy_count
            
            timestamp = datetime.now().strftime("%H:%M:%S")
            
            if new_sells > 0:
                print(f"\n[{timestamp}] 🎉 NEW SELL DETECTED!")
                print(f"   Recent sells: {sell_count} (up from {last_sell_count})")
                for sell in recent_sells[:new_sells]:
                    print(f"   ✅ {sell['product']}: ${sell['value']:.2f} @ {sell['time']}")
            
            if new_buys > 0:
                print(f"\n[{timestamp}] 📈 New buy: {buy_count} total")
            
            # Show summary
            sell_ratio = (sell_count / buy_count * 100) if buy_count > 0 else 0
            status = "✅ HEALTHY" if sell_ratio > 50 else "⚠️ LOW" if sell_ratio > 20 else "❌ CRITICAL"
            
            print(f"[{timestamp}] BUY: {buy_count} | SELL: {sell_count} | Ratio: {sell_ratio:.1f}% {status}")
            
            last_sell_count = sell_count
            last_buy_count = buy_count
            
            time.sleep(30)
            
        except KeyboardInterrupt:
            raise
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(30)

except KeyboardInterrupt:
    print("\n\n✅ Monitoring stopped")
    print("="*70)
