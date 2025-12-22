#!/usr/bin/env python3
"""Check actual USD value of crypto holdings"""
import os
import sys
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, '/workspaces/Nija')

from bot.broker_manager import CoinbaseBroker

broker = CoinbaseBroker()
if not broker.connect():
    print("❌ Connection failed")
    sys.exit(1)

print("\n" + "="*80)
print("💰 CRYPTO HOLDINGS VALUE CHECK")
print("="*80 + "\n")

balance_info = broker.get_account_balance()
print(f"Cash (USD): ${balance_info.get('usd', 0):.2f}")
print(f"Cash (USDC): ${balance_info.get('usdc', 0):.2f}")
print(f"\nCrypto Holdings:")
print("-" * 80)

crypto_dict = balance_info.get('crypto', {})
total_crypto_value = 0

for symbol, quantity in crypto_dict.items():
    if quantity > 0.00000001:
        try:
            product_id = f"{symbol}-USD"
            ticker = broker.client.get_product(product_id)
            # Handle both dict and object responses
            if hasattr(ticker, 'price'):
                price = float(ticker.price)
            elif isinstance(ticker, dict):
                price = float(ticker.get('price', 0))
            else:
                price = float(str(ticker).split("price='")[1].split("'")[0])
            
            value = quantity * price
            total_crypto_value += value
            print(f"{symbol:8s}: {quantity:20.8f} × ${price:12.2f} = ${value:12.2f}")
        except Exception as e:
            print(f"{symbol:8s}: {quantity:20.8f} (unable to price: {e})")

print("-" * 80)
print(f"Total Crypto Value: ${total_crypto_value:.2f}")
print(f"Total Cash: ${balance_info.get('trading_balance', 0):.2f}")
print(f"GRAND TOTAL: ${total_crypto_value + balance_info.get('trading_balance', 0):.2f}")
print("="*80 + "\n")
