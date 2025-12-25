#!/usr/bin/env python3
"""
Verify liquidation success: Check transaction history and final balance
"""
import os
import sys
from datetime import datetime, timedelta
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

from dotenv import load_dotenv
load_dotenv()

try:
    from coinbase.rest import RESTClient
except ImportError:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))
    from coinbase.rest import RESTClient

def main():
    print("\n" + "="*80)
    print("✅ LIQUIDATION VERIFICATION REPORT")
    print("="*80)
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    # Initialize client
    api_key = os.getenv('COINBASE_API_KEY')
    api_secret = os.getenv('COINBASE_API_SECRET')
    
    if not api_key or not api_secret:
        print("❌ ERROR: Missing API credentials")
        return False
    
    try:
        client = RESTClient(
            api_key=api_key,
            api_secret=api_secret
        )
        
        # ============================================================
        # PART 1: CHECK RECENT ORDERS (Transaction History)
        # ============================================================
        print("="*80)
        print("PART 1: RECENT SELLS - VERIFICATION")
        print("="*80 + "\n")
        
        print("📊 Checking orders from the last 30 minutes...\n")
        
        recent_sells = []
        total_sell_volume = 0
        
        try:
            # Get recent orders
            orders = client.get_orders(
                order_status='FILLED',
                product_id=None,
                limit=100
            )
            
            order_list = getattr(orders, 'orders', [])
            now = datetime.utcnow()
            thirty_min_ago = now - timedelta(minutes=30)
            
            for order in order_list:
                created_at_str = getattr(order, 'created_at', '')
                
                # Parse timestamp
                try:
                    if isinstance(created_at_str, str):
                        created_at = datetime.fromisoformat(created_at_str.replace('Z', '+00:00'))
                    else:
                        created_at = created_at_str
                    
                    # Check if order is from last 30 minutes
                    if created_at > thirty_min_ago:
                        side = getattr(order, 'side', 'UNKNOWN')
                        
                        if side == 'SELL':
                            product_id = getattr(order, 'product_id', 'UNKNOWN')
                            order_id = getattr(order, 'order_id', 'UNKNOWN')
                            filled_size = float(getattr(order, 'filled_size', 0))
                            filled_value = float(getattr(order, 'filled_value', 0))
                            status = getattr(order, 'status', 'UNKNOWN')
                            
                            recent_sells.append({
                                'product_id': product_id,
                                'order_id': order_id,
                                'size': filled_size,
                                'value': filled_value,
                                'status': status,
                                'timestamp': created_at
                            })
                            
                            total_sell_volume += filled_value
                            
                            print(f"✅ SELL ORDER")
                            print(f"   Product: {product_id}")
                            print(f"   Amount: {filled_size:.8f}")
                            print(f"   USD Value: ${filled_value:.2f}")
                            print(f"   Order ID: {order_id}")
                            print(f"   Status: {status}")
                            print(f"   Time: {created_at.strftime('%H:%M:%S')}\n")
                
                except Exception as e:
                    continue
            
            if not recent_sells:
                print("⚠️  No recent SELL orders found in the last 30 minutes")
                print("   (Orders may have been from earlier, check manually in Coinbase)\n")
            else:
                print(f"🎯 Total Recent Sells: {len(recent_sells)}")
                print(f"💰 Total USD Value: ${total_sell_volume:.2f}\n")
        
        except Exception as e:
            print(f"⚠️  Could not fetch order history: {e}\n")
        
        # ============================================================
        # PART 2: CHECK CURRENT BALANCES
        # ============================================================
        print("\n" + "="*80)
        print("PART 2: CURRENT ACCOUNT BALANCE - VERIFICATION")
        print("="*80 + "\n")
        
        print("📊 Fetching current balances...\n")
        
        accounts = client.get_accounts()
        account_list = getattr(accounts, 'accounts', [])
        
        total_usd_cash = 0
        crypto_holdings = []
        
        for account in account_list:
            currency = getattr(account, 'currency', 'UNKNOWN')
            available = getattr(account, 'available_balance', {})
            
            if hasattr(available, 'value'):
                balance = float(available.value)
            else:
                balance = float(available.get('value', 0) if isinstance(available, dict) else 0)
            
            if balance > 0.001:  # Show only meaningful balances
                if currency in ['USD', 'USDC']:
                    total_usd_cash += balance
                    print(f"💵 {currency}: ${balance:.2f}")
                else:
                    crypto_holdings.append({
                        'currency': currency,
                        'balance': balance
                    })
                    print(f"🪙 {currency}: {balance:.8f}")
        
        # ============================================================
        # FINAL VERDICT
        # ============================================================
        print("\n" + "="*80)
        print("LIQUIDATION STATUS")
        print("="*80 + "\n")
        
        if crypto_holdings:
            print("❌ INCOMPLETE: Still holding crypto")
            print(f"\n   Remaining positions ({len(crypto_holdings)}):\n")
            for holding in crypto_holdings:
                print(f"   • {holding['currency']}: {holding['balance']:.8f}")
            print("\n   ACTION: Check Coinbase interface for failed orders")
            return False
        else:
            print("✅ COMPLETE: All crypto liquidated!")
            print(f"\n   Current cash balance: ${total_usd_cash:.2f}")
            print("   Status: 100% in USD/USDC - NO MORE BLEEDING")
            
            if total_sell_volume > 0:
                print(f"\n   Proceeds from sales: ${total_sell_volume:.2f}")
            
            return True
        
        print("\n" + "="*80 + "\n")
    
    except Exception as e:
        print(f"❌ ERROR: {str(e)}\n")
        return False

if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
