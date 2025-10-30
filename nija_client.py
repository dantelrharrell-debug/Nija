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

# --- Load API keys from environment ---
COINBASE_API_KEY = os.getenv("COINBASE_API_KEY")
COINBASE_API_SECRET = os.getenv("COINBASE_API_SECRET")
COINBASE_API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE", None)  # optional

if not COINBASE_API_KEY or not COINBASE_API_SECRET:
    logger.error("[NIJA] Missing Coinbase API key or secret — cannot trade live")
    raise RuntimeError("Missing Coinbase API credentials for live trading")

# --- REST client import ---
try:
    from coinbase_advanced_py.rest_client import RESTClient
    USE_DUMMY = False
    logger.info("[NIJA] Live RESTClient instantiated (no passphrase required)")
    client = RESTClient(api_key=COINBASE_API_KEY, api_secret=COINBASE_API_SECRET)
except Exception as e:
    USE_DUMMY = True
    logger.warning(f"[NIJA] Live RESTClient unavailable — using DummyClient. Error: {e}")

# --- DummyClient fallback (for dev, should never hit if keys are present) ---
if USE_DUMMY:
    class DummyClient:
        def get_account_balances(self):
            return {"USD": 1000.0}

        def get_price(self, product_id):
            return 50000.0

        def place_order(self, **kwargs):
            logger.info(f"[NIJA-DUMMY] Would place order: {kwargs}")
            return kwargs

    client = DummyClient()
    logger.warning("[NIJA] DummyClient initialized — no live trades will occur")
