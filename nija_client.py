# nija_client.py
import os
import sys
import logging
from decimal import Decimal
import time

# --- Add local libs folder so Python can find libraries without installing ---
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "libs"))

# --- Setup logging ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_client")

# --- Try importing CoinbaseClient ---
CoinbaseClient = None
try:
    from coinbase_advanced_py.client import CoinbaseClient
    logger.info("[NIJA] Successfully imported CoinbaseClient")
except ModuleNotFoundError:
    logger.warning("[NIJA] CoinbaseClient not available. Using DummyClient")

# --- Fallback DummyClient if needed ---
class DummyClient:
    def __init__(self, *args, **kwargs):
        logger.info("[NIJA] DummyClient initialized — trading simulated")

    def place_order(self, **kwargs):
        logger.info(f"[NIJA] Simulated order: {kwargs}")
        return {"status": "simulated", "details": kwargs}

# --- Initialize client ---
if CoinbaseClient is not None:
    client = CoinbaseClient(
        api_key=os.getenv("COINBASE_API_KEY"),
        api_secret=os.getenv("COINBASE_API_SECRET"),
        passphrase=os.getenv("COINBASE_API_PASSPHRASE")  # optional
    )
    logger.info("[NIJA] Live RESTClient instantiated")
else:
    client = DummyClient()

# --- Example function to place a trade ---
def place_trade(product_id, side, size, price=None):
    """
    product_id: 'BTC-USD'
    side: 'buy' or 'sell'
    size: amount in crypto
    price: optional limit price
    """
    order = {
        "product_id": product_id,
        "side": side,
        "size": str(size)
    }
    if price:
        order["price"] = str(price)

    if CoinbaseClient is not None:
        result = client.place_order(**order)
        logger.info(f"[NIJA] Live trade placed: {result}")
        return result
    else:
        result = client.place_order(**order)
        return result
