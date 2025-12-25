#!/usr/bin/env python3
"""
Check Coinbase transaction history to find where funds went
"""
import os
import sys
from datetime import datetime, timedelta
from coinbase.rest import RESTClient

def check_credentials():
    """Verify API credentials are present"""
    api_key = os.getenv('COINBASE_API_KEY')
    api_secret = os.getenv('COINBASE_API_SECRET')
    
    if not api_key or not api_secret:
        print("❌ ERROR: Missing Coinbase API credentials")
        print("\nRequired environment variables:")
        print("  - COINBASE_API_KEY")
        print("  - COINBASE_API_SECRET")
        print("\nMake sure these are set in your .env file")
        return False
    
    print("✅ API credentials found")
    return True

def format_amount(amount, currency="USD"):
    """Format amount with currency symbol"""
    try:
        amt = float(amount)
        if currency == "USD":
            return f"${amt:,.2f}"
        else:
            return f"{amt:.8f} {currency}"
    except:
        return str(amount)

def analyze_transaction_history():
    """Fetch and analyze Coinbase transaction history"""
    
    if not check_credentials():
        return
    
    try:
        print("\n" + "="*80)
        print("🔍 COINBASE TRANSACTION HISTORY ANALYSIS")
        print("="*80)
        
        client = RESTClient(
            api_key=os.getenv('COINBASE_API_KEY'),
            api_secret=os.getenv('COINBASE_API_SECRET')
        )
        
        # Get all portfolios
        print("\n📂 Fetching portfolios...")
        try:
            portfolios = client.get_portfolios()
            print(f"   Found {len(portfolios.get('portfolios', []))} portfolio(s)")
        except Exception as e:
            print(f"   ⚠️ Could not fetch portfolios: {e}")
            portfolios = {'portfolios': []}
        
        # Get account balances
        print("\n💰 Current Account Balances:")
        print("-" * 80)
        
        try:
            accounts = client.get_accounts()
            total_usd = 0.0
            usd_found = False
            
            for account in accounts.get('accounts', []):
                balance = float(account.get('available_balance', {}).get('value', 0))
                currency = account.get('currency', 'UNKNOWN')
                
                if balance > 0.001:  # Show only non-zero balances
                    print(f"   {currency:10} {format_amount(balance, currency)}")
                    
                    if currency == "USD":
                        total_usd = balance
                        usd_found = True
            
            if usd_found:
                print(f"\n   💵 Total USD Balance: ${total_usd:.2f}")
            else:
                print("\n   ⚠️ No USD balance found")
                
        except Exception as e:
            print(f"   ❌ Error fetching accounts: {e}")
        
        # Get recent orders (trades)
        print("\n\n📊 Recent Trading Activity (Last 30 Days):")
        print("-" * 80)
        
        try:
            # Get orders from the last 30 days
            end_date = datetime.utcnow()
            start_date = end_date - timedelta(days=30)
            
            # Advanced Trade API v3 - list orders
            orders = client.list_orders(
                product_id=None,  # All products
                order_status=['FILLED', 'CANCELLED', 'EXPIRED'],
                limit=100,
                start_date=start_date.isoformat(),
                end_date=end_date.isoformat()
            )
            
            filled_orders = []
            cancelled_orders = []
            
            for order in orders.get('orders', []):
                status = order.get('status', 'UNKNOWN')
                if status == 'FILLED':
                    filled_orders.append(order)
                elif status in ['CANCELLED', 'EXPIRED']:
                    cancelled_orders.append(order)
            
            print(f"\n   ✅ Filled Orders: {len(filled_orders)}")
            print(f"   ❌ Cancelled/Expired: {len(cancelled_orders)}")
            
            if filled_orders:
                print("\n   Recent Filled Orders:")
                print("   " + "-" * 76)
                
                total_buy_usd = 0.0
                total_sell_usd = 0.0
                
                for order in filled_orders[:20]:  # Show last 20
                    product_id = order.get('product_id', 'UNKNOWN')
                    side = order.get('side', 'UNKNOWN')
                    filled_size = order.get('filled_size', 0)
                    filled_value = float(order.get('filled_value', 0))
                    avg_price = float(order.get('average_filled_price', 0))
                    created_time = order.get('created_time', '')
                    
                    # Parse timestamp
                    try:
                        dt = datetime.fromisoformat(created_time.replace('Z', '+00:00'))
                        time_str = dt.strftime('%Y-%m-%d %H:%M:%S')
                    except:
                        time_str = created_time[:19]
                    
                    print(f"   {time_str} | {product_id:15} | {side:4} | {format_amount(filled_value)}")
                    
                    if side == 'BUY':
                        total_buy_usd += filled_value
                    else:
                        total_sell_usd += filled_value
                
                print("\n   Summary:")
                print(f"   Total BUY value:  {format_amount(total_buy_usd)}")
                print(f"   Total SELL value: {format_amount(total_sell_usd)}")
                print(f"   Net flow:         {format_amount(total_sell_usd - total_buy_usd)}")
                
            else:
                print("\n   ℹ️ No filled orders found in the last 30 days")
                
        except Exception as e:
            print(f"   ❌ Error fetching orders: {e}")
            import traceback
            traceback.print_exc()
        
        # Get transfers (deposits/withdrawals)
        print("\n\n💸 Transfers (Deposits & Withdrawals):")
        print("-" * 80)
        
        try:
            # This might not be available in all API versions
            # Try to get transaction history
            print("   ⚠️ Transfer history requires additional API permissions")
            print("   Check your Coinbase.com account directly for:")
            print("   - Deposits from bank/card")
            print("   - Withdrawals to bank/wallet")
            print("   - Transfers between Coinbase products")
            
        except Exception as e:
            print(f"   ℹ️ Transfer history not available via API: {e}")
        
        # Summary
        print("\n\n" + "="*80)
        print("📋 SUMMARY & RECOMMENDATIONS")
        print("="*80)
        
        print("\nTo find where your funds went:")
        print("1. Log into Coinbase.com")
        print("2. Go to 'Portfolio' → 'Transactions'")
        print("3. Filter by date range (last 30-60 days)")
        print("4. Look for:")
        print("   - Large withdrawals")
        print("   - Transfers to other wallets")
        print("   - Failed trades with fees")
        print("   - Conversions between cryptocurrencies")
        
        print("\n💡 Next Steps:")
        if total_usd < 10:
            print("   ⚠️ Current balance too low for trading")
            print("   → Deposit at least $50-$100 to start trading")
        else:
            print("   ✅ Balance sufficient for trading")
            print("   → Check if bot is running and executing trades")
        
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    analyze_transaction_history()
