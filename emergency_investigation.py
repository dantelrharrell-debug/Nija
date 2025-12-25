#!/usr/bin/env python3
"""
Emergency investigation: Check for open orders and recent filled orders
"""
import sys
sys.path.insert(0, 'bot')

from broker_manager import BrokerManager

def main():
    print("\n" + "="*80)
    print("🚨 EMERGENCY INVESTIGATION - Why Is Money Disappearing?")
    print("="*80)
    
    try:
        broker = BrokerManager()
        
        # Check for OPEN orders that might be waiting to execute
        print("\n1️⃣ CHECKING FOR OPEN/PENDING ORDERS...")
        print("-" * 80)
        
        try:
            open_orders = broker.client.list_orders(
                limit=100,
                order_status=['OPEN', 'PENDING']
            )
            
            if hasattr(open_orders, 'orders'):
                order_list = open_orders.orders
            else:
                order_list = []
            
            if order_list:
                print(f"\n   🚨 FOUND {len(order_list)} OPEN ORDERS!")
                print("   These will execute when you deposit money!\n")
                
                for order in order_list:
                    product_id = getattr(order, 'product_id', 'UNKNOWN')
                    side = getattr(order, 'side', 'UNKNOWN')
                    size = getattr(order, 'size', 'UNKNOWN')
                    order_type = getattr(order, 'order_type', 'UNKNOWN')
                    order_id = getattr(order, 'order_id', 'UNKNOWN')
                    
                    print(f"   ⚠️ {product_id} | {side} | Size: {size} | Type: {order_type}")
                    print(f"      Order ID: {order_id}")
                
                print("\n   ❗ THESE ORDERS NEED TO BE CANCELLED!")
                
            else:
                print("   ✅ No open orders found")
                
        except Exception as e:
            print(f"   ⚠️ Could not check open orders: {e}")
        
        # Check recent FILLED orders
        print("\n\n2️⃣ CHECKING RECENT FILLED ORDERS (Last 20)...")
        print("-" * 80)
        
        try:
            filled_orders = broker.client.list_orders(
                limit=20,
                order_status=['FILLED']
            )
            
            if hasattr(filled_orders, 'orders'):
                order_list = filled_orders.orders
            else:
                order_list = []
            
            if order_list:
                print(f"\n   Found {len(order_list)} recent filled orders:\n")
                
                total_spent = 0.0
                
                for i, order in enumerate(order_list, 1):
                    product_id = getattr(order, 'product_id', 'UNKNOWN')
                    side = getattr(order, 'side', 'UNKNOWN')
                    
                    if hasattr(order, 'filled_value'):
                        filled_value = float(order.filled_value)
                    else:
                        filled_value = 0.0
                    
                    if hasattr(order, 'average_filled_price'):
                        avg_price = float(order.average_filled_price)
                    else:
                        avg_price = 0.0
                    
                    created_time = getattr(order, 'created_time', 'UNKNOWN')[:19]
                    
                    print(f"   {i}. {created_time} | {product_id:15} | {side:4} | ${filled_value:8.2f}")
                    
                    if side == 'BUY':
                        total_spent += filled_value
                
                print(f"\n   💸 Total spent on BUY orders: ${total_spent:.2f}")
                print(f"   ⚠️ This is where your money went!")
                
            else:
                print("   No filled orders found (shouldn't be possible if money disappeared)")
                
        except Exception as e:
            print(f"   ⚠️ Could not check filled orders: {e}")
        
        # Check current balance
        print("\n\n3️⃣ CURRENT BALANCE...")
        print("-" * 80)
        
        balance = broker.get_total_balance()
        print(f"   Current USD: ${balance:.2f}")
        
        # Check if bot is running
        print("\n\n4️⃣ CHECKING IF BOT IS RUNNING...")
        print("-" * 80)
        
        import subprocess
        result = subprocess.run(['ps', 'aux'], capture_output=True, text=True)
        
        bot_processes = []
        for line in result.stdout.split('\n'):
            if 'python' in line.lower() and any(x in line for x in ['trading_strategy', 'main.py', 'bot.py', 'webhook']):
                bot_processes.append(line)
        
        if bot_processes:
            print(f"   🚨 FOUND {len(bot_processes)} BOT PROCESS(ES) RUNNING!")
            for proc in bot_processes:
                print(f"   {proc[:120]}")
            print("\n   ⚠️ Bot is actively placing orders!")
        else:
            print("   ✅ No bot processes detected")
        
        # Summary and action plan
        print("\n\n" + "="*80)
        print("📋 DIAGNOSIS & IMMEDIATE ACTIONS")
        print("="*80)
        
        print("\n🔍 What's Happening:")
        print("   Every time you deposit $5+, the bot immediately:")
        print("   1. Detects sufficient balance")
        print("   2. Places BUY orders")
        print("   3. Orders get filled")
        print("   4. Account goes to $0")
        
        print("\n⚠️ Why This Is Bad:")
        print("   • $5 orders are too small (fees eat profits)")
        print("   • No money left for position management")
        print("   • Can't scale positions or take profits")
        print("   • Each trade loses money to fees")
        
        print("\n✅ IMMEDIATE ACTIONS NEEDED:")
        print("   1. CANCEL all open orders (if any found above)")
        print("   2. STOP the bot from running")
        print("   3. DEPOSIT $50-100 (not just $5)")
        print("   4. UPDATE bot settings for minimum position size")
        print("   5. RESTART bot with proper capital")
        
        print("\n💡 Why $50-100 is Critical:")
        print("   • Bot can take $10-20 positions (viable with fees)")
        print("   • Enough buffer for multiple positions")
        print("   • Can manage positions properly")
        print("   • Fees become smaller % of trade")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
