#!/usr/bin/env python3
"""
AUTO-SELL ALL CRYPTO - No prompts, just sells everything
"""
import os
import sys
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, '/workspaces/Nija')

from bot.broker_manager import CoinbaseBroker
import logging
import time

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')

def main():
    print("\n" + "="*80)
    print("🔥 AUTO-LIQUIDATE ALL CRYPTO POSITIONS")
    print("="*80 + "\n")
    
    broker = CoinbaseBroker()
    
    if not broker.connect():
        print("❌ Connection failed")
        return
    
    print("✅ Connected\n")
    
    # Get balance using the SAME method the bot uses (portfolio breakdown)
    balance_info = broker.get_account_balance()
    crypto_holdings = balance_info.get('crypto', {})
    
    print(f"💰 Trading Balance: ${balance_info.get('trading_balance', 0):.2f}")
    print(f"🪙 Crypto Holdings from portfolio breakdown:\n")
    
    crypto_positions = []
    
    for currency, quantity in crypto_holdings.items():
        if quantity > 0.00000001:
            try:
                product_id = f"{currency}-USD"
                ticker = broker.client.get_product(product_id)
                # Handle both dict and object responses
                if hasattr(ticker, 'price'):
                    price = float(ticker.price)
                elif isinstance(ticker, dict):
                    price = float(ticker.get('price', 0))
                else:
                    # Parse from string representation
                    price_str = str(ticker)
                    if "price='" in price_str:
                        price = float(price_str.split("price='")[1].split("'")[0])
                    else:
                        price = 0
                value = quantity * price
            except Exception as e:
                print(f"   Warning: Couldn't price {currency}: {e}")
                price = 0
                value = 0
            
            crypto_positions.append({
                'symbol': currency,
                'quantity': quantity,
                'price': price,
                'value': value,
                'product_id': f"{currency}-USD"
            })
    
    if not crypto_positions:
        print("✅ No crypto to sell - all funds already in cash\n")
        
        # Show current balance
        balance_info = broker.get_account_balance()
        print(f"Trading Balance: ${balance_info.get('trading_balance', 0):.2f}\n")
        return
    
    print(f"🪙 Found {len(crypto_positions)} crypto position(s):\n")
    total_value = 0
    for pos in crypto_positions:
        print(f"   {pos['symbol']:8s} | {pos['quantity']:15.8f} | ${pos['value']:10.2f}")
        total_value += pos['value']
    
    print(f"\n   Total Value: ${total_value:.2f}")
    print("\n🔥 Selling ALL positions in 3 seconds...")
    time.sleep(3)
    
    sold = 0
    proceeds = 0
    
    for pos in crypto_positions:
        print(f"\n📤 Selling {pos['quantity']:.8f} {pos['symbol']}...", end=" ")
        
        try:
            result = broker.place_market_order(
                symbol=pos['product_id'],
                side='SELL',
                quantity=pos['quantity'],
                size_type='base'  # CRITICAL: Use base_size for crypto quantity
            )
            
            if result and result.get('success'):
                sold += 1
                proceeds += pos['value']
                print(f"✅ SOLD (~${pos['value']:.2f})")
            else:
                print(f"❌ FAILED: {result.get('error', 'Unknown')}")
        except Exception as e:
            print(f"❌ ERROR: {str(e)}")
        
        time.sleep(0.3)
    
    print("\n" + "="*80)
    print(f"✅ Sold {sold}/{len(crypto_positions)} positions")
    print(f"💰 Total proceeds: ~${proceeds:.2f}")
    print("\n⏳ Waiting for settlement...")
    time.sleep(5)
    
    # Show updated balance
    balance_info = broker.get_account_balance()
    print(f"\n💵 Updated Trading Balance: ${balance_info.get('trading_balance', 0):.2f}")
    print("="*80 + "\n")

if __name__ == "__main__":
    main()
