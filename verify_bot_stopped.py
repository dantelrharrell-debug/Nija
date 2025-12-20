#!/usr/bin/env python3
"""
Verify that NIJA bot is stopped by checking recent trading activity
"""
import os
import sys
from datetime import datetime, timedelta

# Load .env
def load_env():
    if os.path.exists('.env'):
        with open('.env', 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    # Handle quoted values
                    value = value.strip().strip('"').strip("'")
                    # For multiline values, just take first line
                    if '\n' in value:
                        os.environ[key] = value
                    else:
                        os.environ[key] = value

load_env()

from coinbase.rest import RESTClient

def check_bot_status():
    print("="*70)
    print("🔍 VERIFYING NIJA BOT IS STOPPED")
    print("="*70)
    
    api_key = os.environ.get('COINBASE_API_KEY')
    api_secret = os.environ.get('COINBASE_API_SECRET')
    
    if not api_key or not api_secret:
        print("\n❌ Missing API credentials in .env file")
        return
    
    try:
        client = RESTClient(api_key=api_key, api_secret=api_secret)
        
        # Get recent orders
        print("\n📋 Checking recent orders...")
        orders = client.list_orders(limit=100)
        
        recent_buys = []
        recent_sells = []
        now = datetime.utcnow()
        
        if hasattr(orders, 'orders'):
            for order in orders.orders:
                try:
                    created_time = order.get('created_time', '')
                    if not created_time:
                        continue
                    
                    # Parse time
                    created = datetime.fromisoformat(created_time.replace('Z', '+00:00'))
                    created = created.replace(tzinfo=None)
                    
                    # Check if within last hour
                    age_minutes = (now - created).total_seconds() / 60
                    
                    if age_minutes < 60:  # Last hour
                        side = order.get('side', '')
                        product = order.get('product_id', '')
                        status = order.get('status', '')
                        size = order.get('order_configuration', {}).get('market_market_ioc', {}).get('quote_size', '0')
                        
                        order_info = {
                            'product': product,
                            'status': status,
                            'age_min': int(age_minutes),
                            'size': size
                        }
                        
                        if side == 'BUY':
                            recent_buys.append(order_info)
                        elif side == 'SELL':
                            recent_sells.append(order_info)
                
                except Exception as e:
                    continue
        
        print(f"\n📊 Trading Activity (Last Hour):")
        print(f"   🛒 BUY orders:  {len(recent_buys)}")
        print(f"   💰 SELL orders: {len(recent_sells)}")
        
        if recent_buys:
            print(f"\n⚠️  Recent BUY orders detected:")
            for order in recent_buys[:10]:
                print(f"      • {order['product']} - {order['status']} ({order['age_min']} min ago)")
            print(f"\n   ❌ BOT MAY STILL BE RUNNING!")
        
        if recent_sells:
            print(f"\n   Recent SELL orders:")
            for order in recent_sells[:5]:
                print(f"      • {order['product']} - {order['status']} ({order['age_min']} min ago)")
        
        if not recent_buys and not recent_sells:
            print(f"\n   ✅ No orders in last hour")
            print(f"   ✅ Bot appears to be STOPPED")
        
        # Check current positions
        print(f"\n💼 Current Crypto Holdings:")
        accounts = client.get_accounts()
        crypto_count = 0
        
        for account in accounts.accounts:
            balance = float(account.get('available_balance', {}).get('value', 0))
            currency = account.get('currency', '')
            
            if balance > 0 and currency not in ['USD', 'USDC', 'USDT']:
                crypto_count += 1
                print(f"   • {currency}: {balance:.8f}")
        
        if crypto_count == 0:
            print(f"   ✅ No crypto positions (all in cash)")
        
        print("\n" + "="*70)
        print("📝 VERDICT:")
        if not recent_buys:
            print("✅ No recent buy orders - Bot is STOPPED")
            print("✅ You can now sell without it being bought back")
        else:
            print("⚠️  Recent buy activity detected!")
            print("⚠️  Bot may still be running or recently stopped")
            print("⚠️  Wait 5 minutes and run this script again")
        print("="*70)
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    check_bot_status()
