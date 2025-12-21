#!/usr/bin/env python3
"""
Quick verification script to check rebalance results:
- Holdings count (should be ≤8)
- USD cash balance (should be ≥$15)
- List of current holdings with values
"""
import sys
import os

# Load .env if available (optional for local runs)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv not available, rely on existing env vars

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

from broker_manager import CoinbaseBroker

def main():
    print("=" * 70)
    print("🔍 REBALANCE VERIFICATION")
    print("=" * 70)
    
    try:
        # Initialize broker
        broker = CoinbaseBroker()
        if not broker.connect():
            print("❌ Failed to connect to Coinbase")
            return 1
        
        # Get USD balance
        balance_data = broker.get_account_balance()
        if isinstance(balance_data, dict):
            usd_balance = float(balance_data.get('trading_balance', 0))
        else:
            usd_balance = float(balance_data) if balance_data else 0.0
        
        # Get positions
        positions = broker.get_positions()
        holdings_count = len(positions) if positions else 0
        
        print(f"\n💰 USD Balance: ${usd_balance:.2f}")
        print(f"📊 Holdings Count: {holdings_count}")
        print()
        
        # Check constraints
        target_cash = 15.0
        max_positions = 8
        
        cash_ok = usd_balance >= target_cash
        count_ok = holdings_count <= max_positions
        
        print("✅ CONSTRAINTS CHECK:")
        print(f"   USD ≥ ${target_cash}: {'✅ PASS' if cash_ok else f'❌ FAIL (${usd_balance:.2f})'}")
        print(f"   Holdings ≤ {max_positions}: {'✅ PASS' if count_ok else f'❌ FAIL ({holdings_count})'}")
        print()
        
        if positions:
            print("📋 CURRENT HOLDINGS:")
            total_value = 0.0
            for i, pos in enumerate(positions, 1):
                symbol = pos.get('symbol', 'UNKNOWN')
                qty = float(pos.get('quantity', 0))
                currency = pos.get('currency', '')
                
                # Try to get current price
                try:
                    candles = broker.get_candles(symbol, '5m', 1)
                    if candles and len(candles) > 0:
                        price = float(candles[0].get('close', 0))
                        value = qty * price
                        total_value += value
                        print(f"   {i:2d}. {symbol:12s} qty={qty:.8f} ${value:.2f}")
                    else:
                        print(f"   {i:2d}. {symbol:12s} qty={qty:.8f} (no price)")
                except Exception as e:
                    print(f"   {i:2d}. {symbol:12s} qty={qty:.8f} (price error)")
            
            print(f"\n   Total Holdings Value: ${total_value:.2f}")
            print(f"   Total Portfolio: ${usd_balance + total_value:.2f}")
        else:
            print("📋 CURRENT HOLDINGS: None")
        
        print()
        print("=" * 70)
        
        if cash_ok and count_ok:
            print("✅ REBALANCE SUCCESSFUL - Bot ready to trade!")
        else:
            print("⚠️  CONSTRAINTS NOT MET - Check deployment logs for rebalance execution")
        
        print("=" * 70)
        
        return 0 if (cash_ok and count_ok) else 1
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(main())
