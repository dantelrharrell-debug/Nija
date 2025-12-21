#!/usr/bin/env python3
"""
Emergency position check and liquidation script
Checks real Coinbase holdings and sells ALL positions immediately
"""

import os
import sys
from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

from broker_manager import CoinbaseBroker

load_dotenv()

def main():
    print("=" * 80)
    print("🚨 EMERGENCY POSITION CHECK & LIQUIDATION")
    print("=" * 80)
    print()
    
    broker = CoinbaseBroker()
    if not broker.connect():
        print("❌ Failed to connect to Coinbase")
        return
    
    print("✅ Connected to Coinbase Advanced Trade")
    print()
    
    # Get ALL account balances
    print("📊 Checking ALL account balances...")
    try:
        accounts = broker.client.get_accounts()
        
        crypto_holdings = []
        total_usd_value = 0
        
        for account in accounts['accounts']:
            balance = float(account['available_balance']['value'])
            if balance > 0:
                currency = account['currency']
                print(f"\n💰 {currency}: {balance}")
                
                if currency != "USD" and currency != "USDC":
                    # Get current price
                    try:
                        ticker = f"{currency}-USD"
                        product = broker.client.get_product(ticker)
                        price = float(product.price)
                        usd_value = balance * price
                        total_usd_value += usd_value
                        
                        crypto_holdings.append({
                            'currency': currency,
                            'balance': balance,
                            'price': price,
                            'usd_value': usd_value,
                            'ticker': ticker
                        })
                        
                        print(f"   Price: ${price:.4f}")
                        print(f"   USD Value: ${usd_value:.2f}")
                        
                    except Exception as e:
                        print(f"   ⚠️ Could not get price: {e}")
        
        print("\n" + "=" * 80)
        print(f"📈 Total Crypto Holdings: ${total_usd_value:.2f}")
        print("=" * 80)
        
        if not crypto_holdings:
            print("\n✅ No crypto positions found - account is clear!")
            return
        
        # Ask to sell all positions
        print(f"\n🔴 Found {len(crypto_holdings)} crypto position(s)")
        print("\n⚠️ SELLING ALL POSITIONS NOW...")
        
        for holding in crypto_holdings:
            print(f"\n🔴 Selling {holding['currency']}...")
            print(f"   Amount: {holding['balance']}")
            print(f"   Current Price: ${holding['price']:.4f}")
            print(f"   USD Value: ${holding['usd_value']:.2f}")
            
            try:
                # Market sell immediately
                import uuid
                order_id = str(uuid.uuid4())
                order = broker.client.market_order_sell(
                    client_order_id=order_id,
                    product_id=holding['ticker'],
                    base_size=str(holding['balance'])
                )
                
                print(f"   ✅ SOLD! Order: {order}")
                
            except Exception as e:
                print(f"   ❌ Error selling: {e}")
                # Try again with slightly less quantity (account for fees)
                try:
                    import uuid
                    order_id = str(uuid.uuid4())
                    adjusted_balance = holding['balance'] * 0.995  # Account for fees
                    order = broker.client.market_order_sell(
                        client_order_id=order_id,
                        product_id=holding['ticker'],
                        base_size=str(adjusted_balance)
                    )
                    print(f"   ✅ SOLD (adjusted)! Order: {order}")
                except Exception as e2:
                    print(f"   ❌ Failed again: {e2}")
        
        print("\n" + "=" * 80)
        print("🏁 Liquidation complete!")
        print("=" * 80)
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
