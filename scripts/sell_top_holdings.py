#!/usr/bin/env python3
"""
Force-sell top holdings (BTC, ETH, SOL) with precision + fallback.
Uses Advanced Trade accounts to determine available sizes.
"""
import os
import sys
import time
from typing import Dict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'bot'))

from broker_manager import CoinbaseBroker  # type: ignore

PRECISION_MAP: Dict[str, int] = {
    'BTC': 8, 'ETH': 6, 'SOL': 4, 'XRP': 2, 'DOGE': 2, 'ADA': 2,
    'SHIB': 0, 'ATOM': 4, 'AVAX': 4, 'LINK': 4, 'UNI': 4, 'MATIC': 2,
    'LTC': 8, 'BCH': 8, 'ETC': 8
}

TARGETS = ["BTC", "ETH", "SOL"]


def get_available_sizes(broker: CoinbaseBroker) -> Dict[str, float]:
    sizes: Dict[str, float] = {}
    try:
        resp = broker.client.get_accounts()
        accounts = getattr(resp, 'accounts', []) or (resp.get('accounts', []) if isinstance(resp, dict) else [])
        for acc in accounts:
            if isinstance(acc, dict):
                currency = acc.get('currency')
                av_val = (acc.get('available_balance') or {}).get('value')
            else:
                currency = getattr(acc, 'currency', None)
                av_bal = getattr(acc, 'available_balance', None)
                av_val = getattr(av_bal, 'value', None)
            try:
                amount = float(av_val or 0)
            except Exception:
                amount = 0.0
            if currency and currency not in ("USD", "USDC") and amount > 0:
                sizes[currency] = amount
    except Exception as e:
        print(f"⚠️ Failed to fetch accounts: {e}")
    return sizes


def sell_symbol(broker: CoinbaseBroker, symbol: str, amount: float) -> bool:
    if amount <= 0:
        print(f"ℹ️ {symbol}: no amount to sell")
        return True
    product_id = f"{symbol}-USD"
    decimals = PRECISION_MAP.get(symbol, 8)
    formatted_amount = f"{amount:.{decimals}f}"
    print(f"🔴 Selling {symbol}: {formatted_amount}")
    import uuid
    order_id = str(uuid.uuid4())
    try:
        broker.client.market_order_sell(
            client_order_id=order_id,
            product_id=product_id,
            base_size=formatted_amount
        )
        print(f"   ✅ ORDER PLACED: {symbol}")
        return True
    except Exception as e:
        print(f"   ❌ Error: {e}")
        # Fallback: sell 99.5%
        try:
            adjusted = amount * 0.995
            adjusted_formatted = f"{adjusted:.{decimals}f}"
            broker.client.market_order_sell(
                client_order_id=order_id,
                product_id=product_id,
                base_size=adjusted_formatted
            )
            print(f"   ✅ ORDER PLACED (adjusted): {symbol}")
            return True
        except Exception as e2:
            print(f"   ❌ Failed again: {e2}")
            return False


def main():
    broker = CoinbaseBroker()
    if not broker.connect():
        print("❌ Failed to connect to Coinbase")
        sys.exit(1)
    print("✅ Connected to Coinbase")

    sizes = get_available_sizes(broker)
    sold_any = False
    for sym in TARGETS:
        amt = sizes.get(sym, 0.0)
        if amt > 0:
            ok = sell_symbol(broker, sym, amt)
            sold_any = sold_any or ok
        else:
            print(f"ℹ️ {sym}: no holdings found")

    # Brief pause to allow settlement
    time.sleep(3)
    try:
        bal = broker.get_account_balance()
        print("📊 UPDATED ACCOUNT:")
        print(f"   Cash: ${bal.get('trading_balance', 0.0):.2f}")
    except Exception as e:
        print(f"⚠️ Failed to refresh balance: {e}")

    if not sold_any:
        print("ℹ️ No target holdings were sold. Ensure assets are in Advanced Trade and not on hold.")


if __name__ == "__main__":
    main()
