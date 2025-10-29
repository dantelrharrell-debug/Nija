# nija_client.py
import os
import logging
from decimal import Decimal
import time

try:
    from coinbase_advanced_py.client import CoinbaseClient
except ModuleNotFoundError:
    CoinbaseClient = None

# --- Setup logging ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_client")

# --- Load environment variables ---
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")

# --- Dry run toggle ---
DRY_RUN = False  # set True to test without real trades

# --- Initialize Coinbase client ---
if CoinbaseClient and API_KEY and API_SECRET and API_PASSPHRASE:
    client = CoinbaseClient(
        api_key=API_KEY,
        api_secret=API_SECRET,
        api_passphrase=API_PASSPHRASE
    )
    logger.info("[NIJA] CoinbaseClient initialized — live trading ready")
else:
    # Fallback dummy client
    class DummyClient:
        def get_accounts(self):
            logger.info("[NIJA-DUMMY] get_accounts called")
            return [{"currency": "USD", "balance": "1000"}]

        def place_order(self, *args, **kwargs):
            logger.info(f"[NIJA-DUMMY] place_order called: {args}, {kwargs}")
            return {"id": "dummy_order", "status": "simulated"}

    client = DummyClient()
    DRY_RUN = True
    logger.warning("[NIJA] Using DummyClient — dry run mode")

# --- Helper functions ---
def get_accounts():
    """Fetch account balances."""
    try:
        accounts = client.get_accounts()
        logger.info(f"[NIJA] Accounts fetched: {accounts}")
        return accounts
    except Exception as e:
        logger.error(f"[NIJA] Failed to fetch accounts: {e}")
        return []

def place_order(side, product_id, size, price=None, order_type="market"):
    """
    Place a trade order.
    side: 'buy' or 'sell'
    product_id: 'BTC-USD', 'ETH-USD', etc.
    size: quantity to buy/sell
    price: limit price (ignored for market orders)
    order_type: 'market' or 'limit'
    """
    if DRY_RUN:
        logger.info(f"[NIJA] Dry run enabled. Order not placed: {side} {size} {product_id} {price}")
        return {"id": "dry_run", "status": "simulated"}

    try:
        order = client.place_order(
            side=side,
            product_id=product_id,
            size=size,
            price=price,
            order_type=order_type
        )
        logger.info(f"[NIJA] Order placed: {order}")
        return order
    except Exception as e:
        logger.error(f"[NIJA] Failed to place order: {e}")
        return {"id": None, "status": "failed"}

# --- Example usage ---
if __name__ == "__main__":
    get_accounts()
    # Example: place_order("buy", "BTC-USD", "0.001")
