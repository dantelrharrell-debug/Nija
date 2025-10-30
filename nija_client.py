# nija_client.py
import os
import logging

# --- Setup logging ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_client")

# --- Read env vars early ---
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")
API_SANDBOX = os.getenv("COINBASE_SANDBOX", "false").lower() == "true"

logger.info(f"[NIJA] Coinbase key present: {API_KEY is not None}")
logger.info(f"[NIJA] Coinbase secret present: {API_SECRET is not None}")
logger.info(f"[NIJA] Coinbase passphrase present: {API_PASSPHRASE is not None}")

# --- Robust import attempts for the Coinbase client ---
LiveCoinbaseClient = None
_import_errors = []

try:
    # most common
    from coinbase_advanced_py.client import CoinbaseClient as LiveCoinbaseClient
    logger.info("[NIJA] Imported coinbase_advanced_py.client")
except Exception as e1:
    _import_errors.append(("coinbase_advanced_py.client", str(e1)))
    try:
        # alternate path some packages use
        from coinbase_advanced_py import client as coinbase_client_mod
        LiveCoinbaseClient = getattr(coinbase_client_mod, "CoinbaseClient", None)
        if LiveCoinbaseClient:
            logger.info("[NIJA] Imported coinbase_advanced_py.client via alternate path")
    except Exception as e2:
        _import_errors.append(("coinbase_advanced_py (alt)", str(e2)))
        try:
            # last-resort: try to import top-level package and inspect
            import importlib
            spec = importlib.util.find_spec("coinbase_advanced_py")
            logger.info(f"[NIJA] find_spec coinbase_advanced_py -> {spec is not None}")
        except Exception as e3:
            _import_errors.append(("importlib.find_spec", str(e3)))

if LiveCoinbaseClient is None:
    logger.warning("[NIJA] CoinbaseClient import attempts failed. Errors: %s", _import_errors)

# --- DummyClient defined inline to avoid relative-import problems ---
class DummyClient:
    def __init__(self):
        logger.info("[NIJA] Initialized DummyClient (no live trades)")

    def buy(self, *args, **kwargs):
        logger.info(f"[DummyClient] Simulated BUY {args} {kwargs}")
        return {"status": "simulated_buy", "args": args, "kwargs": kwargs}

    def sell(self, *args, **kwargs):
        logger.info(f"[DummyClient] Simulated SELL {args} {kwargs}")
        return {"status": "simulated_sell", "args": args, "kwargs": kwargs}

    # Provide commonly-used method names used elsewhere in your code
    def get_accounts(self):
        logger.info("[DummyClient] get_accounts called")
        return []

    def get_account_balances(self):
        logger.info("[DummyClient] get_account_balances called")
        return {"USD": 1000.0, "BTC": 0.0}

# --- Decide whether to use live client or dummy ---
USE_DUMMY = True
client = None

if LiveCoinbaseClient:
    if not (API_KEY and API_SECRET and API_PASSPHRASE):
        logger.warning("[NIJA] CoinbaseClient available but one or more API creds missing (passphrase required). Falling back to DummyClient.")
        USE_DUMMY = True
        client = DummyClient()
    else:
        try:
            # instantiate the real client
            client = LiveCoinbaseClient(
                api_key=API_KEY,
                api_secret=API_SECRET,
                passphrase=API_PASSPHRASE,
                sandbox=API_SANDBOX
            )
            USE_DUMMY = False
            logger.info("[NIJA] Live CoinbaseClient initialized and ready for trading")
        except Exception as e:
            logger.error(f"[NIJA] Failed to initialize LiveCoinbaseClient: {e}")
            logger.info("[NIJA] Falling back to DummyClient")
            USE_DUMMY = True
            client = DummyClient()
else:
    logger.warning("[NIJA] Live CoinbaseClient not found; using DummyClient")
    client = DummyClient()

# Expose names for importers
__all__ = ["client", "USE_DUMMY"]
