#!/usr/bin/env python3
"""
Check ALL funds and crypto positions, then sell any crypto holdings
"""
import os
import sys
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

sys.path.insert(0, '/workspaces/Nija')

from bot.broker_manager import CoinbaseBroker
import logging
import time

logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(message)s')

def main():
    print("\n" + "="*80)
    print("🔍 COMPREHENSIVE FUND & CRYPTO CHECK + LIQUIDATION")
    print("="*80 + "\n")
    
    broker = CoinbaseBroker()
    
    if not broker.connect():
        print("❌ Failed to connect to Coinbase")
        return False
    
    print("✅ Connected to Coinbase\n")
    
    # Get all balances
    print("💰 Fetching ALL balances...")
    balance_info = broker.get_account_balance()
    
    consumer_usd = balance_info.get('consumer_usd', 0)
    consumer_usdc = balance_info.get('consumer_usdc', 0)
    advanced_usd = balance_info.get('usd', 0)
    advanced_usdc = balance_info.get('usdc', 0)
    trading_balance = balance_info.get('trading_balance', 0)
    
    print("\n" + "="*80)
    print("💵 CASH BALANCES:")
    print("="*80)
    print(f"Consumer USD:  ${consumer_usd:.2f}")
    print(f"Consumer USDC: ${consumer_usdc:.2f}")
    print(f"Advanced USD:  ${advanced_usd:.2f}")
    print(f"Advanced USDC: ${advanced_usdc:.2f}")
    print(f"─────────────────────────────")
    print(f"TOTAL CASH:    ${consumer_usd + consumer_usdc + advanced_usd + advanced_usdc:.2f}")
    
    # Get all crypto positions - use raw API call to get everything
    print("\n" + "="*80)
    print("🪙 CHECKING ALL CRYPTO POSITIONS...")
    print("="*80)
    
    try:
        # Get all accounts from v3 API
        accounts_response = broker.client.get_accounts()
        all_accounts = accounts_response.get('accounts', [])
        
        crypto_positions = []
        total_crypto_value = 0
        
        for account in all_accounts:
            currency = account.get('currency', '')
            available_balance = float(account.get('available_balance', {}).get('value', 0))
            
            # Skip USD/USDC (those are cash)
            if currency in ['USD', 'USDC']:
                continue
            
            # If there's any balance, it's a crypto position
            if available_balance > 0.00000001:  # Even tiny amounts
                # Try to get current price
                try:
                    product_id = f"{currency}-USD"
                    ticker = broker.client.get_product(product_id)
                    price = float(ticker.get('price', 0))
                    market_value = available_balance * price
                except:
                    # If we can't get price, estimate at 0
                    price = 0
                    market_value = 0
                
                crypto_positions.append({
                    'symbol': currency,
                    'quantity': available_balance,
                    'price': price,
                    'value': market_value
                })
                total_crypto_value += market_value
        
        if crypto_positions:
            print(f"\n✅ Found {len(crypto_positions)} crypto position(s):\n")
            for pos in crypto_positions:
                print(f"   {pos['symbol']:8s} | Qty: {pos['quantity']:15.8f} | Price: ${pos['price']:10.2f} | Value: ${pos['value']:10.2f}")
            
            print(f"\n{'─'*80}")
            print(f"TOTAL CRYPTO VALUE: ${total_crypto_value:.2f}")
            print(f"{'─'*80}")
            
            # Ask to sell
            print("\n" + "="*80)
            print("🔥 LIQUIDATION OPTIONS:")
            print("="*80)
            print("\n1. Sell ALL crypto positions now")
            print("2. Show details only (don't sell)")
            print("3. Cancel")
            
            choice = input("\nEnter choice (1/2/3): ").strip()
            
            if choice == "1":
                print("\n🔥 SELLING ALL CRYPTO POSITIONS...")
                print("="*80)
                
                sold_count = 0
                total_proceeds = 0
                
                for pos in crypto_positions:
                    symbol = pos['symbol']
                    quantity = pos['quantity']
                    
                    print(f"\n📤 Selling {quantity:.8f} {symbol}...")
                    
                    try:
                        # Place market sell order
                        product_id = f"{symbol}-USD"
                        
                        result = broker.place_market_order(
                            symbol=product_id,
                            side='SELL',
                            quantity=quantity
                        )
                        
                        if result and result.get('success'):
                            sold_count += 1
                            proceeds = pos['value']
                            total_proceeds += proceeds
                            print(f"   ✅ SOLD {symbol} for ~${proceeds:.2f}")
                        else:
                            error_msg = result.get('error', 'Unknown error')
                            print(f"   ❌ Failed to sell {symbol}: {error_msg}")
                    
                    except Exception as e:
                        print(f"   ❌ Error selling {symbol}: {str(e)}")
                    
                    # Brief pause between orders
                    time.sleep(0.5)
                
                print("\n" + "="*80)
                print("📊 LIQUIDATION SUMMARY:")
                print("="*80)
                print(f"Positions sold: {sold_count}/{len(crypto_positions)}")
                print(f"Total proceeds: ~${total_proceeds:.2f}")
                print("\n⏳ Waiting 5 seconds for orders to settle...")
                time.sleep(5)
                
                # Check balance again
                print("\n🔄 Refreshing balance...")
                balance_info = broker.get_account_balance()
                new_trading_balance = balance_info.get('trading_balance', 0)
                
                print("\n" + "="*80)
                print("💰 UPDATED BALANCE:")
                print("="*80)
                print(f"Trading Balance: ${new_trading_balance:.2f}")
                print(f"Gain from sales: ~${new_trading_balance - trading_balance:.2f}")
                
            elif choice == "2":
                print("\n✅ Details shown above. No sales executed.")
            else:
                print("\n❌ Cancelled.")
        
        else:
            print("\n✅ No crypto positions found - all funds are in cash")
        
        # Final summary
        total_cash = consumer_usd + consumer_usdc + advanced_usd + advanced_usdc
        grand_total = total_cash + total_crypto_value
        
        print("\n" + "="*80)
        print("📊 FINAL SUMMARY:")
        print("="*80)
        print(f"Cash:         ${total_cash:.2f}")
        print(f"Crypto:       ${total_crypto_value:.2f}")
        print(f"─────────────────────────────")
        print(f"TOTAL VALUE:  ${grand_total:.2f}")
        
        if consumer_usd + consumer_usdc > 0:
            print(f"\n⚠️  You have ${consumer_usd + consumer_usdc:.2f} in Consumer wallet")
            print("   Transfer to Advanced Trade to use for trading")
        
        print("\n" + "="*80)
        
    except Exception as e:
        print(f"\n❌ Error checking positions: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    return True

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
