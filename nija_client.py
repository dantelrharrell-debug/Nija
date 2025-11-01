# nija_client.py
"""
Robust client loader for Nija trading bot.

Provides:
- init_client() -> returns a client instance (DummyClient or CoinbaseClient)
- DummyClient for local/dev use
- Safe import attempts with logging and no NameErrors
"""

import os
import logging
import importlib
from decimal import Decimal

# ----------------------
# Configure logger
# ----------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_client")

# ----------------------
# Environment API keys
# ----------------------
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")

# ----------------------
# Dummy client (safe fallback)
# ----------------------
class DummyClient:
    def __init__(self):
        logger.info("[NIJA] Using DummyClient (simulated trading).")
        self.name = "DummyClient"

    def place_buy(self, product_id, amount):
        logger.info(f"[DummyClient] Simulated BUY {{'product_id': {product_id}, 'amount': {amount}}}")
        return {"status": "simulated", "product_id": product_id, "amount": amount}

    def place_sell(self, product_id, amount):
        logger.info(f"[DummyClient] Simulated SELL {{'product_id': {product_id}, 'amount': {amount}}}")
        return {"status": "simulated", "product_id": product_id, "amount": amount}

    def get_usd_balance(self) -> Decimal:
        return Decimal("100.00")

# ----------------------
# Discover potential real clients
# ----------------------
_client_candidates = []
_import_attempts = []

def _discover_clients():
    tries = [
        ("coinbase.rest.RESTClient", "from coinbase.rest import RESTClient"),
        ("coinbase.rest_client.RESTClient", "from coinbase.rest_client import RESTClient"),
        ("coinbase_advanced_py.client.RESTClient", "from coinbase_advanced_py.client import RESTClient"),
        ("coinbase_advanced_py.RESTClient", "from coinbase_advanced_py import RESTClient"),
        ("coinbase.RESTClient", "from coinbase import RESTClient"),
    ]
    for _, hint in tries:
        try:
            parts = hint.replace("from ", "").split(" import ")
            mod_name, cls_name = parts[0].strip(), parts[1].strip()
            mod = importlib.import_module(mod_name)
            cls = getattr(mod, cls_name)
            _client_candidates.append((f"{mod_name}.{cls_name}", cls))
            _import_attempts.append((hint, "ok"))
            logger.info(f"[NIJA] Import succeeded: {hint}")
        except Exception as e:
            _import_attempts.append((hint, f"failed: {e}"))
            logger.debug(f"[NIJA-DEBUG] Import attempt {hint} failed: {e}")

_discover_clients()

# ----------------------
# Instantiate and test client class
# ----------------------
def _instantiate_and_test(client_cls, *args, **kwargs):
    try:
        inst = client_cls(*args, **kwargs)
    except Exception as e:
        logger.debug(f"[NIJA-DEBUG] Instantiation failed for {client_cls} args={args} kwargs={kwargs}: {e}")
        return None
    try:
        if hasattr(inst, "get_spot_account_balances"):
            _ = inst.get_spot_account_balances()
        elif hasattr(inst, "get_accounts"):
            _ = inst.get_accounts()
        return inst
    except Exception as e:
        logger.debug(f"[NIJA-DEBUG] Test call failed for {client_cls}: {e}")
        return None

# ----------------------
# Public API: init_client
# ----------------------
def init_client():
    """
    Returns a client instance:
    - Real Coinbase client if API_KEY/SECRET present and works
    - DummyClient otherwise
    Modern Coinbase uses JWT auth; passphrase not required.
    """
    logger.info(f"[NIJA] API_KEY present: {'yes' if API_KEY else 'no'}")
    logger.info(f"[NIJA] API_SECRET present: {'yes' if API_SECRET else 'no'}")

    if not (API_KEY and API_SECRET):
        logger.warning("[NIJA] Missing API key/secret — using DummyClient")
        return DummyClient()

    for name, cls in _client_candidates:
        logger.info(f"[NIJA] Trying candidate client: {name}")

        # Positional JWT-style authentication
        inst = _instantiate_and_test(cls, API_KEY, API_SECRET)
        if inst:
            logger.info(f"[NIJA] Authenticated {name} using API_KEY/API_SECRET only (JWT)")
            return inst

        # Keyword args
        inst = _instantiate_and_test(cls, api_key=API_KEY, api_secret=API_SECRET)
        if inst:
            logger.info(f"[NIJA] Authenticated {name} using keyword args (JWT)")
            return inst

    # If none worked,
