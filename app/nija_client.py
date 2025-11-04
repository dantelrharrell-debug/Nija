# nija_client.py
import os
from coinbase_advanced import Client
import logging

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("nija_client")

# Initialize Coinbase Advanced client
client = Client(
    api_key=os.getenv("COINBASE_API_KEY"),
    api_secret=os.getenv("COINBASE_API_SECRET"),
    base_url="https://api.coinbase.com"
)

def get_usd_balance():
    """Fetch USD spot balance"""
    try:
        accounts = client.get_accounts()
        for acc in accounts:
            if acc['currency'] == 'USD':
                balance = float(acc['balance']['amount'])
                log.info(f"USD Balance: {balance}")
                return balance
        return 0.0
    except Exception as e:
        log.error(f"Failed to fetch USD balance: {e}")
        return 0.0

def place_order(side, product, size, price=None):
    """Place a simple market or limit order"""
    try:
        if price:
            order = client.place_limit_order(
                product_id=product,
                side=side,
                price=str(price),
                size=str(size)
            )
        else:
            order = client.place_market_order(
                product_id=product,
                side=side,
                size=str(size)
            )
        log.info(f"Order placed: {order}")
        return order
    except Exception as e:
        log.error(f"Failed to place order: {e}")
        return None
