#!/usr/bin/env python3
"""
Check if NIJA bot is actually stopped by looking for recent trading activity
"""
import os
import sys
sys.path.insert(0, '/workspaces/Nija')

# Load .env file first
from dotenv import load_dotenv
load_dotenv()

from bot.broker_manager import CoinbaseBroker
from datetime import datetime, timedelta
import logging

logging.basicConfig(level=logging.WARNING)

def main():
    print("\n" + "="*70)
    print("🔍 CHECKING IF NIJA BOT IS STOPPED")
    print("="*70 + "\n")
    
    broker = CoinbaseBroker()
    if not broker.connect():
        print("❌ Failed to connect to Coinbase")
        return
    
    print("✅ Connected to Coinbase API\n")
    
    # Get recent orders
    print("📋 Checking for recent trading activity...\n")
    
    try:
        # Get orders from the last hour
        orders = broker.client.list_orders(limit=100)
        
        recent_buys = []
        recent_sells = []
        now = datetime.utcnow()
        
        if hasattr(orders, 'orders'):
            for order in orders.orders:
                try:
                    created_time = order.get('created_time', '')
                    if not created_time:
                        continue
                    
                    # Parse timestamp
                    created = datetime.fromisoformat(created_time.replace('Z', '+00:00'))
                    created = created.replace(tzinfo=None)
                    
                    # Calculate age in minutes
                    age_minutes = (now - created).total_seconds() / 60
                    
                    # Only check last 30 minutes
                    if age_minutes < 30:
                        side = order.get('side', '')
                        product = order.get('product_id', '')
                        status = order.get('status', '')
                        
                        order_info = {
                            'product': product,
                            'status': status,
                            'age': int(age_minutes),
                            'time': created.strftime('%H:%M:%S')
                        }
                        
                        if side == 'BUY':
                            recent_buys.append(order_info)
                        elif side == 'SELL':
                            recent_sells.append(order_info)
                
                except Exception as e:
                    continue
        
        print("="*70)
        print("📊 TRADING ACTIVITY (Last 30 Minutes):")
        print("="*70)
        print(f"   🛒 BUY orders:  {len(recent_buys)}")
        print(f"   💰 SELL orders: {len(recent_sells)}")
        
        if recent_buys:
            print(f"\n   ⚠️  Recent BUY orders found:")
            for i, order in enumerate(recent_buys[:10], 1):
                print(f"      {i}. {order['product']} at {order['time']} ({order['age']} min ago) - {order['status']}")
        
        if recent_sells:
            print(f"\n   Recent SELL orders:")
            for i, order in enumerate(recent_sells[:5], 1):
                print(f"      {i}. {order['product']} at {order['time']} ({order['age']} min ago) - {order['status']}")
        
        print("\n" + "="*70)
        print("📝 VERDICT:")
        print("="*70)
        
        if not recent_buys and not recent_sells:
            print("✅ NO TRADING ACTIVITY in last 30 minutes")
            print("✅ Bot appears to be STOPPED")
            print("✅ Safe to sell crypto - it won't be bought back")
        elif recent_sells and not recent_buys:
            print("✅ Only SELL orders detected (no buys)")
            print("✅ Bot is STOPPED - you're manually selling")
        elif recent_buys:
            print("⚠️  BUY ORDERS DETECTED!")
            print("⚠️  Bot may still be running or just stopped")
            print("⚠️  Wait 5 more minutes and check again")
        
        print("="*70 + "\n")
        
        # Also check current positions
        print("💼 Current Crypto Holdings:")
        print("-"*70)
        
        accounts = broker.client.get_accounts()
        crypto_count = 0
        
        for account in accounts.accounts:
            balance = float(account.get('available_balance', {}).get('value', 0))
            currency = account.get('currency', '')
            
            if balance > 0.00000001 and currency not in ['USD', 'USDC', 'USDT']:
                crypto_count += 1
                print(f"   • {currency}: {balance:.8f}")
        
        if crypto_count == 0:
            print("   ✅ No crypto positions (all cash)")
        else:
            print(f"\n   Total: {crypto_count} different cryptocurrencies")
        
        print()
        
    except Exception as e:
        print(f"❌ Error checking orders: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
