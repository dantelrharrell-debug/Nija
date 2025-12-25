#!/usr/bin/env python3
"""
EMERGENCY: Liquidate all bleeding positions IMMEDIATELY
Frees up capital for 8-position trading strategy
"""

import os
import sys
import json
from dotenv import load_dotenv

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

from broker_manager import CoinbaseBroker

load_dotenv()

def main():
    print("=" * 80)
    print("🚨 EMERGENCY LIQUIDATION - SELL ALL BLEEDING POSITIONS")
    print("=" * 80)
    print()
    
    # Connect to broker
    broker = CoinbaseBroker()
    if not broker.connect():
        print("❌ Failed to connect to Coinbase")
        return
    
    print("✅ Connected to Coinbase")
    print()
    
    # Get current balance
    balance_info = broker.get_account_balance()
    print("📊 CURRENT ACCOUNT:")
    print(f"   Cash: ${balance_info['trading_balance']:.2f}")
    print()

    # Build actual crypto quantities from Advanced Trade accounts
    crypto_qty = {}
    try:
        accounts_resp = broker.client.get_accounts()
        accounts = getattr(accounts_resp, 'accounts', []) or (accounts_resp.get('accounts', []) if isinstance(accounts_resp, dict) else [])
        for acc in accounts:
            if isinstance(acc, dict):
                currency = acc.get('currency')
                av_val = (acc.get('available_balance') or {}).get('value')
            else:
                currency = getattr(acc, 'currency', None)
                av_val = getattr(getattr(acc, 'available_balance', None), 'value', None)
            try:
                amount = float(av_val or 0)
            except Exception:
                amount = 0.0
            if currency and currency not in ("USD", "USDC") and amount > 0:
                crypto_qty[currency] = amount
    except Exception as e:
        print(f"⚠️ Failed to fetch accounts for crypto quantities: {e}")

    if crypto_qty:
        print("🪙 CRYPTO HOLDINGS (WILL SELL):")
        for symbol, amount in crypto_qty.items():
            product_id = f"{symbol}-USD"
            try:
                product = broker.client.get_product(product_id)
                price = float(getattr(product, 'price', 0) or (product.get('price') if isinstance(product, dict) else 0))
                value = amount * price
                print(f"   • {symbol}: {amount:.8f} @ ${price:.2f} = ${value:.2f}")
            except Exception:
                print(f"   • {symbol}: {amount:.8f} (price unavailable)")
    
    print()
    print("=" * 80)
    print("SELLING ALL POSITIONS...")
    print("=" * 80)
    print()
    
    total_proceeds = 0
    positions_sold = 0
    precision_map = {
        'XRP': 2, 'DOGE': 2, 'ADA': 2, 'SHIB': 0,
        'BTC': 8, 'ETH': 6, 'SOL': 4, 'ATOM': 4,
        'AVAX': 4, 'LINK': 4, 'UNI': 4, 'MATIC': 2,
        'LTC': 8, 'BCH': 8, 'ETC': 8
    }
    
    if crypto_qty:
        for symbol, amount in crypto_qty.items():
            if amount > 0.00001:  # Skip dust
                product_id = f"{symbol}-USD"
                try:
                    # Get current price
                    product = broker.client.get_product(product_id)
                    price = float(getattr(product, 'price', 0) or (product.get('price') if isinstance(product, dict) else 0))
                    value = amount * price
                    
                    # Format amount with correct precision
                    decimals = precision_map.get(symbol, 8)
                    formatted_amount = f"{amount:.{decimals}f}"
                    
                    print(f"🔴 Selling {symbol}...")
                    print(f"   Amount: {formatted_amount}")
                    print(f"   Price: ${price:.2f}")
                    print(f"   Est. Proceeds: ${value:.2f}")
                    
                    # Execute market sell
                    import uuid
                    order_id = str(uuid.uuid4())
                    
                    try:
                        order = broker.client.market_order_sell(
                            client_order_id=order_id,
                            product_id=product_id,
                            base_size=formatted_amount
                        )
                        print(f"   ✅ ORDER PLACED")
                        total_proceeds += value
                        positions_sold += 1
                    except Exception as e:
                        print(f"   ❌ Error: {e}")
                        # Try with 99.5% of amount for fees
                        try:
                            adjusted = amount * 0.995
                            adjusted_formatted = f"{adjusted:.{decimals}f}"
                            order = broker.client.market_order_sell(
                                client_order_id=order_id,
                                product_id=product_id,
                                base_size=adjusted_formatted
                            )
                            print(f"   ✅ ORDER PLACED (adjusted)")
                            total_proceeds += (adjusted * price)
                            positions_sold += 1
                        except Exception as e2:
                            print(f"   ❌ Failed again: {e2}")
                    
                    print()
                
                except Exception as e:
                    print(f"❌ {symbol}: {e}")
                    print()
    
    print("=" * 80)
    print("LIQUIDATION COMPLETE")
    print("=" * 80)
    print(f"Positions sold: {positions_sold}")
    print(f"Est. capital freed: ${total_proceeds:.2f}")
    print()
    # Fetch updated cash balance
    try:
        updated = broker.get_account_balance()
        print("📊 UPDATED ACCOUNT:")
        print(f"   Cash: ${updated.get('trading_balance', 0.0):.2f}")
        if updated.get('trading_balance', 0.0) < 10.0:
            print("   ⚠️ Cash still below trading threshold. Ensure assets are in Advanced Trade and not on hold.")
    except Exception as e:
        print(f"⚠️ Failed to refresh balance: {e}")
    print()
    print("💰 NEXT STEPS:")
    print("1. Wait 30 seconds for orders to settle")
    print("2. Bot will auto-configure for 8-position trading")
    print("3. Equal capital per position = better profits")
    print("4. 1.5% stop loss prevents bleeding")
    print("5. Bot restarts automatically with full capital")
    print()

if __name__ == "__main__":
    main()
