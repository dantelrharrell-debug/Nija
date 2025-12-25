#!/usr/bin/env python3
"""
Deep check of ACTUAL current trading activity
"""
import os
import sys
sys.path.insert(0, '/workspaces/Nija')

from dotenv import load_dotenv
load_dotenv()

from bot.broker_manager import CoinbaseBroker
from datetime import datetime, timedelta
import logging

logging.basicConfig(level=logging.WARNING)

def main():
    print("\n" + "="*70)
    print("🚨 REAL-TIME TRADING ACTIVITY CHECK")
    print("="*70 + "\n")
    
    broker = CoinbaseBroker()
    if not broker.connect():
        print("❌ Failed to connect")
        return
    
    print("✅ Connected\n")
    
    # Get ALL recent orders
    print("📋 Fetching ALL recent orders...\n")
    
    try:
        orders = broker.client.list_orders(limit=200)
        
        all_buys = []
        all_sells = []
        
        if hasattr(orders, 'orders'):
            for order in orders.orders:
                try:
                    created_time = order.get('created_time', '')
                    if not created_time:
                        continue
                    
                    created = datetime.fromisoformat(created_time.replace('Z', '+00:00'))
                    created = created.replace(tzinfo=None)
                    
                    side = order.get('side', '')
                    product = order.get('product_id', '')
                    status = order.get('status', '')
                    
                    order_info = {
                        'product': product,
                        'status': status,
                        'time': created.strftime('%Y-%m-%d %H:%M:%S'),
                        'created': created
                    }
                    
                    if side == 'BUY':
                        all_buys.append(order_info)
                    elif side == 'SELL':
                        all_sells.append(order_info)
                
                except Exception as e:
                    continue
        
        # Sort by time (most recent first)
        all_buys.sort(key=lambda x: x['created'], reverse=True)
        all_sells.sort(key=lambda x: x['created'], reverse=True)
        
        print("="*70)
        print("📊 LAST 10 BUY ORDERS:")
        print("="*70)
        if all_buys:
            for i, order in enumerate(all_buys[:10], 1):
                print(f"{i:2d}. {order['time']} | {order['product']:15s} | {order['status']}")
        else:
            print("   No BUY orders found")
        
        print("\n" + "="*70)
        print("📊 LAST 10 SELL ORDERS:")
        print("="*70)
        if all_sells:
            for i, order in enumerate(all_sells[:10], 1):
                print(f"{i:2d}. {order['time']} | {order['product']:15s} | {order['status']}")
        else:
            print("   No SELL orders found")
        
        # Check timestamps
        now = datetime.utcnow()
        if all_buys:
            latest_buy = all_buys[0]
            buy_age = (now - latest_buy['created']).total_seconds() / 60
            print(f"\n⏰ Most recent BUY: {latest_buy['time']} ({int(buy_age)} minutes ago)")
        
        if all_sells:
            latest_sell = all_sells[0]
            sell_age = (now - latest_sell['created']).total_seconds() / 60
            print(f"⏰ Most recent SELL: {latest_sell['time']} ({int(sell_age)} minutes ago)")
        
        # Count recent activity
        recent_buys = [o for o in all_buys if (now - o['created']).total_seconds() < 3600]
        recent_sells = [o for o in all_sells if (now - o['created']).total_seconds() < 3600]
        
        print("\n" + "="*70)
        print("🔥 LAST HOUR SUMMARY:")
        print("="*70)
        print(f"   BUY orders:  {len(recent_buys)}")
        print(f"   SELL orders: {len(recent_sells)}")
        
        if len(recent_buys) > len(recent_sells):
            print("\n⚠️  MORE BUYING THAN SELLING!")
            print("⚠️  Bot may still be active or was recently active")
        elif len(recent_sells) > len(recent_buys):
            print("\n✅ More selling than buying - you're manually selling")
        
        print("\n" + "="*70)
        print("🎯 VERDICT:")
        print("="*70)
        
        if recent_buys:
            print("❌ BUY ACTIVITY DETECTED IN LAST HOUR!")
            print("❌ Bot is either:")
            print("   1. Still running somewhere")
            print("   2. Was just stopped recently")
            print("   3. Running on a different service/location")
            print("\n🔍 Check Railway dashboard again!")
        else:
            print("✅ No buy activity in last hour")
            print("✅ Bot is stopped")
        
        print("="*70 + "\n")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
