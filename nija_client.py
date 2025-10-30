# nija_client.py
import os
import logging

# --- logging ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_client")

# --- read env ---
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")
API_PASSPHRASE = os.getenv("COINBASE_API_PASSPHRASE")  # may be optional for some SDK auth flows
API_SANDBOX = os.getenv("COINBASE_SANDBOX", "false").lower() == "true"

logger.info(f"[NIJA] Coinbase key present: {API_KEY is not None}")
logger.info(f"[NIJA] Coinbase secret present: {API_SECRET is not None}")
logger.info(f"[NIJA] Coinbase passphrase present: {API_PASSPHRASE is not None}")

# --- Dummy client inline (robust fallback) ---
class DummyClient:
    def __init__(self):
        logger.info("[NIJA] Initialized DummyClient (no live trades)")

    def buy(self, *args, **kwargs):
        logger.info(f"[DummyClient] buy called: {args} {kwargs}")
        return {"status": "simulated_buy"}

    def sell(self, *args, **kwargs):
        logger.info(f"[DummyClient] sell called: {args} {kwargs}")
        return {"status": "simulated_sell"}

    # name aliases used elsewhere in your code
    def get_accounts(self):
        logger.info("[DummyClient] get_accounts called")
        return []

    def get_account_balances(self):
        logger.info("[DummyClient] get_account_balances called")
        return {"USD": 1000.0, "BTC": 0.0}

    # Example market order interface used in README
    def market_order_buy(self, **kwargs):
        logger.info(f"[DummyClient] market_order_buy {kwargs}")
        return {"status": "simulated_market_buy", "kwargs": kwargs}

# --- Try to import official SDK in known locations ---
LiveClientClass = None
_import_errors = []

# 1) Preferred official SDK import (per README): from coinbase.rest import RESTClient
try:
    from coinbase.rest import RESTClient as _RESTClient
    LiveClientClass = _RESTClient
    logger.info("[NIJA] Imported coinbase.rest.RESTClient")
except Exception as e:
    _import_errors.append(("coinbase.rest.RESTClient", str(e)))
    try:
        # some installs expose RESTClient directly on coinbase
        import coinbase
        LiveClientClass = getattr(coinbase, "RESTClient", None)
        if LiveClientClass:
            logger.info("[NIJA] Imported RESTClient from top-level coinbase package")
    except Exception as e2:
        _import_errors.append(("coinbase top-level", str(e2)))

# 2) Try coinbase_advanced_py package (older code paths)
if LiveClientClass is None:
    try:
        from coinbase_advanced_py.client import CoinbaseClient as _CBAdvClient
        LiveClientClass = _CBAdvClient
        logger.info("[NIJA] Imported coinbase_advanced_py.client.CoinbaseClient")
    except Exception as e3:
        _import_errors.append(("coinbase_advanced_py.client", str(e3)))
        try:
            import importlib.util
            spec = importlib.util.find_spec("coinbase_advanced_py")
            logger.info(f"[NIJA] coinbase_advanced_py find_spec: {spec is not None}")
        except Exception as e4:
            _import_errors.append(("importlib.find_spec", str(e4)))

if LiveClientClass is None:
    logger.warning("[NIJA] CoinbaseClient import attempts failed. Errors: %s", _import_errors)

# --- Instantiate client if possible, else DummyClient ---
USE_DUMMY = True
client = None

if LiveClientClass:
    # Try to instantiate with the commonly-used constructor signatures.
    # RESTClient usually constructs without args using env vars, or with api_key/api_secret.
    try:
        # Try no-arg constructor (reads env vars)
        client = LiveClientClass()  # type: ignore
        USE_DUMMY = False
        logger.info("[NIJA] Live RESTClient/CoinbaseClient instantiated with no-args (env keys used)")
    except Exception as e_noargs:
        logger.info("[NIJA] No-arg instantiation failed: %s", e_noargs)
        # Try constructor that accepts api_key and api_secret
        try:
            client = LiveClientClass(api_key=API_KEY, api_secret=API_SECRET)  # type: ignore
            USE_DUMMY = False
            logger.info("[NIJA] Live RESTClient/CoinbaseClient instantiated with api_key/api_secret")
        except Exception as e_args:
            logger.error("[NIJA] Failed to instantiate Live client: %s", e_args)
            client = None

if client is None:
    logger.warning("[NIJA] Falling back to DummyClient")
    client = DummyClient()
    USE_DUMMY = True
else:
    logger.info("[NIJA] Using live client (USE_DUMMY=%s)", USE_DUMMY)

# Normalize/export common function names that other modules expect
# (so existing code calling client.get_account_balances, client.get_accounts, client.market_order_buy still works)
def _wrap_live_methods(c):
    """
    If the live client uses different method names, add aliases so the rest of the code works.
    """
    # RESTClient example exposes get_accounts, market_order_buy etc — if any aliasing needed, do here.
    # We only add wrappers if missing.
    if not hasattr(c, "get_account_balances") and hasattr(c, "get_accounts"):
        def _balances():
            # attempt to call get_accounts and reduce to balances shape
            try:
                accs = c.get_accounts()
                # try to produce a simple balances dict
                return {a.get("currency", "unknown"): a.get("available_balance", 0) for a in accs}
            except Exception:
                return {}
        setattr(c, "get_account_balances", _balances)

    # if market_order_buy not present but generic method exists, we can add a small wrapper
    if not hasattr(c, "market_order_buy") and hasattr(c, "market_order"):
        def _m_buy(**kwargs):
            return c.market_order(side="buy", **kwargs)
        setattr(c, "market_order_buy", _m_buy)

try:
    if not USE_DUMMY:
        _wrap_live_methods(client)
except Exception as e:
    logger.warning(f"[NIJA] Wrapping live client methods failed: {e}")

# Export names
__all__ = ["client", "USE_DUMMY"]
