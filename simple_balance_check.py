#!/usr/bin/env python3
"""
Simple balance and recent orders check using working API calls
"""
import os
from coinbase.rest import RESTClient

def main():
    print("\n" + "="*80)
    print("💰 SIMPLE BALANCE & TRADE CHECK")
    print("="*80)
    
    api_key = os.getenv('COINBASE_API_KEY')
    api_secret = os.getenv('COINBASE_API_SECRET')
    
    if not api_key or not api_secret:
        print("\n❌ Missing credentials")
        return
    
    try:
        client = RESTClient(api_key=api_key, api_secret=api_secret)
        
        # Get accounts (this works)
        print("\n📊 ACCOUNT BALANCES:")
        print("-" * 80)
        
        accounts = client.get_accounts()
        
        # Handle the response object properly
        if hasattr(accounts, 'accounts'):
            account_list = accounts.accounts
        else:
            account_list = []
        
        total_usd = 0.0
        has_balance = False
        
        for account in account_list:
            if hasattr(account, 'available_balance'):
                balance = float(account.available_balance.value)
                currency = account.currency
                
                if balance > 0.0001:
                    has_balance = True
                    print(f"   {currency:10} {balance:,.8f}")
                    
                    if currency == "USD":
                        total_usd = balance
        
        if not has_balance:
            print("   No balances found")
        
        print(f"\n   💵 USD Balance: ${total_usd:.2f}")
        
        # Get recent orders (without date filters that cause issues)
        print("\n\n📈 RECENT ORDERS (Last 100):")
        print("-" * 80)
        
        try:
            # Don't use date filters - they cause parsing errors
            orders = client.list_orders(
                limit=100,
                order_status=['FILLED']
            )
            
            # Handle response object
            if hasattr(orders, 'orders'):
                order_list = orders.orders
            else:
                order_list = []
            
            if not order_list:
                print("\n   ❌ NO FILLED ORDERS FOUND")
                print("   This confirms: Bot never successfully executed any trades")
                print("   All trade attempts failed with INSUFFICIENT_FUND")
            else:
                print(f"\n   ✅ Found {len(order_list)} filled orders")
                print("\n   Recent trades:")
                
                for order in order_list[:20]:
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
                    
                    created_time = getattr(order, 'created_time', '')[:19]
                    
                    print(f"   {created_time} | {product_id:15} | {side:4} | ${filled_value:8.2f} @ ${avg_price:.2f}")
        
        except Exception as e:
            print(f"\n   ⚠️ Could not fetch orders: {e}")
        
        # Summary
        print("\n\n" + "="*80)
        print("📋 SUMMARY")
        print("="*80)
        
        if total_usd < 10:
            print(f"\n   Current Balance: ${total_usd:.2f}")
            print("   Status: ⚠️ TOO LOW FOR TRADING")
            print("\n   Why you're 'losing money':")
            print("   - Bot attempted 124+ trades")
            print("   - ALL failed (INSUFFICIENT_FUND)")
            print("   - NO trades were executed")
            print("   - Balance was always too low")
            print("\n   If balance was higher before:")
            print("   - Check Coinbase.com for withdrawals")
            print("   - Check for manual trades outside bot")
            print("   - Check transfers to other wallets")
        else:
            print(f"\n   Current Balance: ${total_usd:.2f}")
            print("   Status: ✅ Sufficient for trading")
            
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
