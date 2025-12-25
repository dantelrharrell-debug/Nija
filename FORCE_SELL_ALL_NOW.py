#!/usr/bin/env python3
"""
FORCE LIQUIDATE ALL CRYPTO - NO EXCEPTIONS
Bypasses all bot logic and sells everything immediately
"""
import os
import sys

# Add bot to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

# Load environment
from dotenv import load_dotenv
load_dotenv()

from broker_manager import CoinbaseBroker

def main():
    print("\n" + "=" * 80)
    print("🚨 FORCE LIQUIDATION - SELLING ALL CRYPTO IMMEDIATELY")
    print("=" * 80)
    
    broker = CoinbaseBroker()
    if not broker.connect():
        print("❌ Failed to connect to Coinbase")
        return 1
    
    # Get all positions
    print("\n📊 Fetching positions...")
    positions = broker.get_positions()
    
    if not positions:
        print("✅ No positions found - account is clear")
        return 0
    
    print(f"\nFound {len(positions)} positions:")
    for i, pos in enumerate(positions, 1):
        symbol = pos.get('symbol', '???')
        balance = pos.get('balance', 0)
        price = pos.get('current_price', 0)
        value = balance * price
        print(f"  {i}. {symbol}: {balance:.8f} @ ${price:.4f} = ${value:.2f}")
    
    print(f"\n🔴 SELLING ALL {len(positions)} POSITIONS...")
    print("=" * 80)
    
    sold = 0
    failed = 0
    
    for i, pos in enumerate(positions, 1):
        symbol = pos.get('symbol', '???')
        currency = pos.get('currency', symbol.split('-')[0])
        balance = pos.get('balance', 0)
        
        print(f"\n[{i}/{len(positions)}] Selling {currency}...")
        
        try:
            result = broker.market_order_sell(
                product_id=symbol,
                base_size=str(balance)
            )
            
            if result and result.get('success'):
                print(f"  ✅ SOLD!")
                sold += 1
            else:
                error = result.get('error', 'Unknown') if result else 'No response'
                print(f"  ❌ Failed: {error}")
                failed += 1
                
        except Exception as e:
            print(f"  ❌ Exception: {e}")
            failed += 1
    
    print("\n" + "=" * 80)
    print("📊 RESULTS:")
    print(f"  ✅ Sold: {sold}/{len(positions)}")
    print(f"  ❌ Failed: {failed}")
    
    # Check final balance
    try:
        balance_data = broker.get_account_balance()
        cash = balance_data.get('trading_balance', 0.0)
        print(f"\n💰 Final Cash Balance: ${cash:.2f}")
    except:
        pass
    
    print("=" * 80 + "\n")
    
    return 0 if failed == 0 else 1

if __name__ == "__main__":
    sys.exit(main())
