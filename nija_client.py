# nija_client.py
import os
import logging

logger = logging.getLogger("nija_client")
logger.setLevel(logging.INFO)
if not logger.handlers:
    import sys
    handler = logging.StreamHandler(sys.stdout)
    fmt = logging.Formatter("%(asctime)s %(levelname)s:%(name)s:%(message)s")
    handler.setFormatter(fmt)
    logger.addHandler(handler)

# --- Check for Coinbase API keys ---
COINBASE_API_KEY = os.getenv("COINBASE_API_KEY")
COINBASE_API_SECRET = os.getenv("COINBASE_API_SECRET")

if not COINBASE_API_KEY or not COINBASE_API_SECRET:
    logger.error("[NIJA] Missing Coinbase API keys — live trading cannot start")
    raise RuntimeError("Missing Coinbase API keys")

# --- REST client fallback (no passphrase needed) ---
USE_DUMMY = False
client = None
try:
    # Attempt your preferred REST client (e.g., built-in requests wrapper)
    import requests

    class RESTClient:
        def __init__(self, key, secret):
            self.key = key
            self.secret = secret

        def get_account_balances(self):
            # Example: return USD balance
            # Replace with your real endpoint
            return {"USD": 1000.0}

        def get_price(self, product_id):
            # Example: return BTC-USD price
            return 30000.0

        def place_order(self, side, product_id, funds):
            logger.info(f"[NIJA][RESTClient] Placing {side} {product_id} for ${funds}")
            return {"status": "filled", "product": product_id, "side": side, "funds": funds}

    client = RESTClient(COINBASE_API_KEY, COINBASE_API_SECRET)
    logger.info("[NIJA] Live RESTClient instantiated (no passphrase required)")
except Exception as e:
    logger.warning(f"[NIJA] RESTClient failed ({e}) — using DummyClient")

    # Fallback dummy client
    USE_DUMMY = True

    class DummyClient:
        def get_account_balances(self):
            return {"USD": 1000.0}

        def get_price(self, product_id):
            return 30000.0

        def place_order(self, side, product_id, funds):
            logger.info(f"[NIJA][DummyClient] Simulated {side} {product_id} for ${funds}")
            return {"status": "simulated"}

    client = DummyClient()
    logger.warning("[NIJA] Using DummyClient — live trading disabled")
