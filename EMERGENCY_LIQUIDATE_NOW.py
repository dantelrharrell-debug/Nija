#!/usr/bin/env python3
"""EMERGENCY: Sell ALL crypto positions immediately"""
import sys
sys.path.insert(0, 'bot')

from broker_manager import BrokerManager
import time

print("\n" + "="*70)
print("🚨 EMERGENCY LIQUIDATION - SELLING ALL CRYPTO NOW")
print("="*70)

broker = BrokerManager()
balance = broker.get_account_balance()

print(f"\n💵 Starting USD: ${balance['usd']:.2f}")
print("\n📊 Crypto Holdings to Sell:")
for symbol, amount in balance['crypto'].items():
    if amount > 0:
        print(f"   {symbol}: {amount:.8f}")

total_sold_value = 0
successful = 0
failed = 0

print("\n" + "="*70)
print("🔴 EXECUTING MARKET SELLS...")
print("="*70)

for symbol, amount in balance['crypto'].items():
    if amount > 0 and symbol != "ATOM":  # Skip ATOM if 0
        pair = f"{symbol}-USD"
        try:
            print(f"\n🔄 Selling {amount:.8f} {symbol}...")
            
            # Place market sell order
            result = broker.place_market_order(
                symbol=pair,
                side="sell",
                size=amount,
                size_type="base"  # Sell by crypto amount, not USD
            )
            
            if result and result.get("status") in ["filled", "partial"]:
                filled_value = float(result.get("filled_value", 0))
                total_sold_value += filled_value
                successful += 1
                print(f"   ✅ SOLD for ${filled_value:.2f}")
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
