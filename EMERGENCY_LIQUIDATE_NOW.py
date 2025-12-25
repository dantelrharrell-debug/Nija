#!/usr/bin/env python3
"""EMERGENCY: Sell ALL crypto positions immediately"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

from broker_manager import CoinbaseBroker
import time

print("\n" + "="*70)
print("🚨 EMERGENCY LIQUIDATION - SELLING ALL CRYPTO NOW")
print("="*70)

broker = CoinbaseBroker()
broker.connect()

# Get current positions
positions = broker.get_positions()

print(f"\n📊 Crypto Holdings to Sell: {len(positions)} positions")
for pos in positions:
    symbol = pos.get('symbol', 'UNKNOWN')
    balance = pos.get('balance', 0)
    print(f"   {symbol}: {balance:.8f}")

total_sold_value = 0
successful = 0
failed = 0

print("\n" + "="*70)
print("🔴 EXECUTING MARKET SELLS...")
print("="*70)

for pos in positions:
    symbol = pos.get('symbol', 'UNKNOWN')
    currency = pos.get('currency', symbol.split('-')[0] if '-' in symbol else symbol)
    balance = pos.get('balance', 0)
    
    if balance <= 0:
        continue
        
    try:
        print(f"\n🔄 Selling {balance:.8f} {currency}...")
        
        # Place market sell order
        result = broker.market_order_sell(
            product_id=symbol,
            base_size=str(balance)
        )
        
        if result and result.get("success"):
            successful += 1
            print(f"   ✅ SOLD {currency}!")
        else:
            failed += 1
                error_msg = result.get("error", result.get("message", "Unknown error"))
                print(f"   ❌ FAILED: {error_msg}")
                
            time.sleep(0.5)  # Rate limit protection
            
        except Exception as e:
            failed += 1
            print(f"   ❌ ERROR selling {symbol}: {e}")

# Get final balance
print("\n" + "="*70)
print("📊 LIQUIDATION COMPLETE")
print("="*70)

final_balance = broker.get_account_balance()
print(f"\n💰 Results:")
print(f"   Total sold value: ${total_sold_value:.2f}")
print(f"   Successful: {successful}")
print(f"   Failed: {failed}")
print(f"\n💵 Final USD Balance: ${final_balance['usd']:.2f}")

# Check for remaining crypto
remaining = {k: v for k, v in final_balance['crypto'].items() if v > 0}
if remaining:
    print(f"\n⚠️  WARNING: Some crypto remains:")
    for symbol, amount in remaining.items():
        print(f"   {symbol}: {amount:.8f}")
else:
    print("\n✅ ALL CRYPTO SOLD")

print("\n" + "="*70)
