#!/usr/bin/env python3
"""
AUTO LIQUIDATION - Non-interactive emergency sell of all crypto
"""
import os
import sys
import time
import logging
from datetime import datetime

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s'
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
    print("🚨 AUTO LIQUIDATION - SELLING ALL CRYPTO NOW")
    print("="*80)
    print(f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    # Get credentials
    api_key = os.getenv('COINBASE_API_KEY')
    api_secret = os.getenv('COINBASE_API_SECRET')
    
    if not api_key or not api_secret:
        print("❌ ERROR: Missing Coinbase credentials")
        return False
    
    try:
        # Initialize Coinbase client
        print("🔐 Connecting to Coinbase...")
        client = RESTClient(
            api_key=api_key,
            api_secret=api_secret
        )
        
        # Fetch all holdings
        print("📊 Fetching holdings...")
        accounts_resp = client.get_accounts()
        accounts = getattr(accounts_resp, 'accounts', [])
        
        crypto_positions = []
        usd_balance = 0
        
        for account in accounts:
            currency = getattr(account, 'currency', None)
            available_balance = getattr(account, 'available_balance', None)
            
            if not currency or available_balance is None:
                continue
            
            balance_value = float(getattr(available_balance, 'value', 0))
            
            if balance_value <= 0:
                continue
            
            if currency in ['USD', 'USDC']:
                usd_balance += balance_value
                print(f"   💵 {currency}: ${balance_value:.2f}")
            else:
                crypto_positions.append({
                    'currency': currency,
                    'balance': balance_value,
                    'symbol': f"{currency}-USD"
                })
                print(f"   🪙 {currency}: {balance_value:.8f}")
        
        if not crypto_positions:
            print("\n✅ No crypto holdings to sell - already all cash")
            return True
        
        print(f"\n💰 Total positions to liquidate: {len(crypto_positions)}")
        
        # Get prices and execute sales
        print("\n" + "="*80)
        print("EXECUTING LIQUIDATION...")
        print("="*80 + "\n")
        
        successful_sales = 0
        failed_sales = 0
        
        for pos in crypto_positions:
            currency = pos['currency']
            symbol = pos['symbol']
            amount = pos['balance']
            
            try:
                # Get current price
                print(f"Selling {currency}...")
                product = client.get_product(symbol)
                current_price = float(getattr(product, 'price', 0))
                current_value = amount * current_price
                
                print(f"  Amount: {amount:.8f} {currency}")
                print(f"  Price: ${current_price:.2f}")
                print(f"  Value: ${current_value:.2f}")
                
                # Place market sell order
                order = client.market_order_sell(
                    client_order_id=f"auto_liq_{currency}_{int(time.time())}",
                    product_id=symbol,
                    quote_size=current_value
                )
                
                order_id = getattr(order, 'order_id', None)
                
                if order_id:
                    print(f"  ✅ Sold! Order ID: {order_id}\n")
                    successful_sales += 1
                else:
                    print(f"  ❌ Order failed\n")
                    failed_sales += 1
                
                # Small delay between orders
                time.sleep(1)
            
            except Exception as e:
                print(f"  ❌ Error: {str(e)}\n")
                failed_sales += 1
        
        # Summary
        print("="*80)
        print("LIQUIDATION SUMMARY")
        print("="*80)
        print(f"✅ Successful: {successful_sales}")
        print(f"❌ Failed: {failed_sales}")
        
        if failed_sales > 0:
            print(f"\n⚠️  WARNING: {failed_sales} positions may not have sold")
            print("   Verify in Coinbase Advanced Trade interface")
        else:
            print("\n✅ All positions liquidated successfully!")
        
        print("\n" + "="*80 + "\n")
        return failed_sales == 0
    
    except Exception as e:
        print(f"\n❌ CRITICAL ERROR: {str(e)}")
        return False

if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
