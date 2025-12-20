#!/usr/bin/env python3
"""
Check if Nija is ACTUALLY trading right now
"""
import os
import sys
sys.path.insert(0, '/workspaces/Nija')

from dotenv import load_dotenv
load_dotenv()

from bot.broker_manager import CoinbaseBroker
from datetime import datetime, timedelta

print("\n" + "="*70)
print("🔍 CHECKING IF NIJA IS SELLING NOW")
print("="*70 + "\n")

broker = CoinbaseBroker()
if not broker.connect():
    print("❌ FAILED TO CONNECT TO COINBASE")
    sys.exit(1)

print("✅ Connected to Coinbase\n")

# 1. Check balance with NEW method
print("💰 BALANCE CHECK (using fixed API):")
print("-" * 70)
balance = broker.get_account_balance()
print(f"Trading Balance: ${balance['trading_balance']:.2f}")
print(f"  - USD:  ${balance['usd']:.2f}")
print(f"  - USDC: ${balance['usdc']:.2f}")

if balance['trading_balance'] > 0:
    print("✅ Bot CAN see funds!\n")
else:
    print("❌ Bot CANNOT see funds - still broken!\n")
    sys.exit(1)

# 2. Check for recent orders
print("📊 RECENT TRADING ACTIVITY:")
print("-" * 70)

try:
    orders = broker.client.list_orders(limit=100)
    
    now = datetime.utcnow()
    last_hour = now - timedelta(hours=1)
    last_5_min = now - timedelta(minutes=5)
    last_30_min = now - timedelta(minutes=30)
    
    recent_buys = []
    recent_sells = []
    
    if hasattr(orders, 'orders'):
        for order in orders.orders:
            created_time = getattr(order, 'created_time', '')
            if not created_time:
                continue
            
            try:
                created = datetime.fromisoformat(created_time.replace('Z', '+00:00')).replace(tzinfo=None)
            except:
                continue
            
            if created < last_hour:
                continue
            
            side = getattr(order, 'side', '')
            product = getattr(order, 'product_id', '')
            status = getattr(order, 'status', '')
            
            order_info = {
                'time': created,
                'product': product,
                'side': side,
                'status': status,
                'age_minutes': (now - created).total_seconds() / 60
            }
            
            if side == 'BUY':
                recent_buys.append(order_info)
            elif side == 'SELL':
                recent_sells.append(order_info)
    
    # Show results
    print(f"Last hour: {len(recent_buys)} BUYS, {len(recent_sells)} SELLS\n")
    
    if recent_buys or recent_sells:
        print("🎯 RECENT ORDERS (last 60 minutes):\n")
        
        all_orders = sorted(recent_buys + recent_sells, key=lambda x: x['time'], reverse=True)
        
        for o in all_orders[:10]:
            age = int(o['age_minutes'])
            emoji = "🟢" if o['side'] == 'BUY' else "🔴"
            print(f"{emoji} {age}m ago - {o['side']} {o['product']} ({o['status']})")
        
        # Check if selling in last 5 minutes
        recent_sells_5min = [s for s in recent_sells if (now - s['time']).total_seconds() < 300]
        recent_buys_5min = [b for b in recent_buys if (now - b['time']).total_seconds() < 300]
        
        print("\n" + "="*70)
        if recent_sells_5min:
            print("✅ YES! NIJA IS ACTIVELY SELLING NOW!")
            print(f"   {len(recent_sells_5min)} SELL order(s) in last 5 minutes")
        elif recent_buys_5min:
            print("✅ YES! NIJA IS ACTIVELY TRADING NOW!")
            print(f"   {len(recent_buys_5min)} BUY order(s) in last 5 minutes")
            print("   (No sells yet, but bot is active)")
        elif recent_sells:
            print("⚠️  NIJA WAS SELLING, BUT NOT RIGHT NOW")
            latest_sell = max(recent_sells, key=lambda x: x['time'])
            age = int(latest_sell['age_minutes'])
            print(f"   Last sell was {age} minutes ago")
        elif recent_buys:
            print("⚠️  NIJA IS TRADING, BUT NO SELLS YET")
            latest_buy = max(recent_buys, key=lambda x: x['time'])
            age = int(latest_buy['age_minutes'])
            print(f"   Last buy was {age} minutes ago")
        else:
            print("❌ NO RECENT TRADING ACTIVITY")
        print("="*70)
    else:
        print("❌ NO ORDERS IN LAST HOUR")
        print("\nPOSSIBLE REASONS:")
        print("1. Railway deployment still in progress (wait 2-3 minutes)")
        print("2. No RSI signals in market yet (bot scans every 2.5 minutes)")
        print("3. Market conditions don't meet entry criteria")
        print("\n💡 TIP: Wait 5 minutes and run this script again")
    
except Exception as e:
    print(f"❌ ERROR checking orders: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "="*70 + "\n")
