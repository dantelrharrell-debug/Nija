#!/usr/bin/env python3
"""
Direct check of Coinbase orders - bypassing broker manager
"""
import os
from coinbase.rest import RESTClient

def main():
    print("\n" + "="*80)
    print("🚨 WHAT'S DRAINING YOUR ACCOUNT? - Direct Coinbase Check")
    print("="*80)
    
    # Get credentials directly
    api_key = os.getenv('COINBASE_API_KEY')
    api_secret = os.getenv('COINBASE_API_SECRET')
    
    if not api_key or not api_secret:
        print("\n❌ Missing credentials - cannot check orders")
        print("Run: source .env && python3 whats_draining_account.py")
        return
    
    # Normalize PEM if needed
    if api_secret and '\\n' in api_secret:
        api_secret = api_secret.replace('\\n', '\n')
    
    try:
        print("\n🔐 Connecting to Coinbase...")
        client = RESTClient(api_key=api_key, api_secret=api_secret)
        print("✅ Connected\n")
        
        # 1. Check for OPEN orders (these drain your account when money appears)
        print("1️⃣ CHECKING FOR OPEN/PENDING ORDERS...")
        print("-" * 80)
        
        try:
            open_orders = client.list_orders(
                limit=100,
                order_status=['OPEN', 'PENDING']
            )
            
            order_list = open_orders.orders if hasattr(open_orders, 'orders') else []
            
            if order_list:
                print(f"\n🚨 FOUND {len(order_list)} OPEN ORDERS!")
                print("⚠️  These will INSTANTLY execute when you deposit money!\n")
                
                total_open_value = 0.0
                
                for order in order_list:
                    product_id = getattr(order, 'product_id', 'UNKNOWN')
                    side = getattr(order, 'side', 'UNKNOWN')
                    order_type = getattr(order, 'order_type', 'UNKNOWN')
                    order_id = getattr(order, 'order_id', 'UNKNOWN')[:20]
                    
                    # Try to get order value
                    if hasattr(order, 'order_configuration'):
                        config = order.order_configuration
                        if hasattr(config, 'market_market_ioc'):
                            value = getattr(config.market_market_ioc, 'quote_size', '0')
                            total_open_value += float(value)
                            print(f"   🔴 {product_id:15} | {side:4} | ${float(value):8.2f} | ID: {order_id}...")
                        else:
                            print(f"   🔴 {product_id:15} | {side:4} | Type: {order_type} | ID: {order_id}...")
                    else:
                        print(f"   🔴 {product_id:15} | {side:4} | Type: {order_type} | ID: {order_id}...")
                
                print(f"\n   💸 Total value of open orders: ${total_open_value:.2f}")
                print("\n   ⚠️  THIS IS WHY YOUR MONEY DISAPPEARS!")
                print("   → When you deposit $5, these orders execute immediately")
                print("   → Account goes to $0 after orders fill")
                print("\n   ✅ SOLUTION: Cancel all these orders (instructions below)")
                
            else:
                print("   ✅ No open orders found")
                print("   If money still disappears, bot is placing orders in real-time")
        
        except Exception as e:
            print(f"   ⚠️  Error checking open orders: {e}")
        
        # 2. Check recent FILLED orders (what already executed)
        print("\n\n2️⃣ RECENT FILLED ORDERS (Last 50)...")
        print("-" * 80)
        
        try:
            filled_orders = client.list_orders(
                limit=50,
                order_status=['FILLED']
            )
            
            order_list = filled_orders.orders if hasattr(filled_orders, 'orders') else []
            
            if not order_list:
                print("   ℹ️  No filled orders found")
            else:
                print(f"\n   Found {len(order_list)} filled orders:\n")
                
                total_buy = 0.0
                total_sell = 0.0
                buy_count = 0
                sell_count = 0
                
                for i, order in enumerate(order_list[:30], 1):
                    product_id = getattr(order, 'product_id', 'UNKNOWN')
                    side = getattr(order, 'side', 'UNKNOWN')
                    filled_value = float(getattr(order, 'filled_value', 0))
                    avg_price = float(getattr(order, 'average_filled_price', 0))
                    created_time = getattr(order, 'created_time', '')[:19]
                    
                    print(f"   {i:2}. {created_time} | {product_id:15} | {side:4} | ${filled_value:8.2f} @ ${avg_price:.4f}")
                    
                    if side == 'BUY':
                        total_buy += filled_value
                        buy_count += 1
                    else:
                        total_sell += filled_value
                        sell_count += 1
                
                print(f"\n   Summary of last {len(order_list)} orders:")
                print(f"   BUY:  {buy_count} orders, ${total_buy:,.2f} spent")
                print(f"   SELL: {sell_count} orders, ${total_sell:,.2f} received")
                print(f"   Net:  ${total_sell - total_buy:+,.2f}")
                
                if total_sell < total_buy:
                    loss = total_buy - total_sell
                    print(f"\n   ❌ NET LOSS: ${loss:.2f}")
                    print(f"   This is where your money went - losing trades!")
                elif total_sell > total_buy:
                    profit = total_sell - total_buy
                    print(f"\n   ✅ NET PROFIT: ${profit:.2f}")
                    print(f"   Your trades were profitable!")
                
        except Exception as e:
            print(f"   ⚠️  Error checking filled orders: {e}")
        
        # 3. Current balance
        print("\n\n3️⃣ CURRENT BALANCE...")
        print("-" * 80)
        
        try:
            accounts = client.get_accounts()
            account_list = accounts.accounts if hasattr(accounts, 'accounts') else []
            
            usd_balance = 0.0
            for account in account_list:
                if account.currency == 'USD':
                    usd_balance = float(account.available_balance.value)
                    break
            
            print(f"   Current USD: ${usd_balance:.2f}")
            
        except Exception as e:
            print(f"   ⚠️  Error checking balance: {e}")
        
        # Summary and actions
        print("\n\n" + "="*80)
        print("📋 WHAT'S HAPPENING & HOW TO FIX IT")
        print("="*80)
        
        print("\n🔍 The Problem:")
        print("   When you deposit $5 into Coinbase:")
        print("   1. Bot (or open orders) detect the money")
        print("   2. Immediately place BUY orders")
        print("   3. Orders execute and buy crypto")
        print("   4. Your USD balance → $0")
        print("   5. You're left holding crypto instead of USD")
        
        print("\n⚠️  Why $5 Orders Are Terrible:")
        print("   • Coinbase fees: ~0.5-1.5% ($0.025-$0.075 per trade)")
        print("   • Spread cost: ~0.1-0.5% ($0.005-$0.025 per trade)")
        print("   • Total cost: $0.03-$0.10 PER TRADE")
        print("   • Need price to move 2-4% just to break even!")
        print("   • With $5, you can't manage positions or scale out")
        
        print("\n✅ HOW TO FIX THIS:")
        print("\n   Step 1: CANCEL ALL OPEN ORDERS")
        print("   -------")
        if order_list:
            print("   Run this command to cancel all:")
            print("   python3 cancel_all_orders.py")
            print("   (I'll create this script for you)")
        else:
            print("   ✅ No open orders to cancel")
        
        print("\n   Step 2: STOP THE BOT")
        print("   -------")
        print("   Make sure bot is not running:")
        print("   ps aux | grep python")
        print("   If you see bot process: kill <PID>")
        
        print("\n   Step 3: DEPOSIT PROPER CAPITAL")
        print("   -------")
        print("   Deposit $50-$100 (NOT $5)")
        print("   Why? $10-20 positions are viable after fees")
        
        print("\n   Step 4: UPDATE BOT SETTINGS")
        print("   -------")
        print("   Set minimum position size to $10")
        print("   (Already done in recent fixes)")
        
        print("\n   Step 5: RESTART BOT")
        print("   -------")
        print("   With $50+ capital, bot can trade properly")
        print("   Monitor first 5-10 trades to verify profitability")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
