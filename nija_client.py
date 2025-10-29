# nija_client.py
import os
import logging
from typing import Any

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_client")

# --- Dummy client fallback (simple, safe) ---
class DummyClient:
    def __init__(self):
        logger.warning("[NIJA-DUMMY] DummyClient initialized (no live Coinbase available).")
    def get_accounts(self):
        logger.info("[NIJA-DUMMY] get_accounts called")
        return [{"currency": "USD", "balance": "1000"}]
    def place_order(self, *args, **kwargs):
        logger.info("[NIJA-DUMMY] place_order called (dry-run)")
        return {"status": "dry-run", "args": args, "kwargs": kwargs}

# --- Attempt to use coinbase_advanced_py (several possible import styles) ---
client: Any = None
coinbase_module = None
try:
    import coinbase_advanced_py as cap
    coinbase_module = cap
    logger.info("[NIJA] Imported coinbase_advanced_py top-level module.")
except Exception:
    try:
        # Some installs expose `coinbase_advanced_py.client`
        from coinbase_advanced_py import client as cap_client
        coinbase_module = cap_client
        logger.info("[NIJA] Imported coinbase_advanced_py.client submodule.")
    except Exception:
        coinbase_module = None

# Also try older/newer coinbase SDKs
rest_client = None
try:
    from coinbase.rest import RESTClient  # some repos expose this
    rest_client = RESTClient
    logger.info("[NIJA] Found coinbase.rest.RESTClient")
except Exception:
    rest_client = None

# envs
COINBASE_API_KEY = os.getenv("COINBASE_API_KEY")
COINBASE_PEM_PATH = os.getenv("COINBASE_API_SECRET_PATH", "/opt/render/project/secrets/coinbase.pem")
COINBASE_PASSPHRASE = os.getenv("COINBASE_PASSPHRASE", None)
SANDBOX = os.getenv("SANDBOX", None)  # optional

# Try to instantiate coinbase_advanced_py's CoinbaseClient if available
if coinbase_module is not None:
    try:
        # Try common locations / names
        if hasattr(coinbase_module, "CoinbaseClient"):
            CoinbaseClient = getattr(coinbase_module, "CoinbaseClient")
        elif hasattr(coinbase_module, "client") and hasattr(coinbase_module.client, "CoinbaseClient"):
            CoinbaseClient = getattr(coinbase_module.client, "CoinbaseClient")
        else:
            CoinbaseClient = None

        if CoinbaseClient is not None:
            # Try constructor variations: minimal args, api_key + pem path, etc.
            try:
                # Prefer pem_file_path if present
                if os.path.exists(COINBASE_PEM_PATH):
                    client = CoinbaseClient(api_key=COINBASE_API_KEY, pem_file_path=COINBASE_PEM_PATH)
                else:
                    # fallback: try api_key only
                    client = CoinbaseClient(api_key=COINBASE_API_KEY)
                logger.info("[NIJA] Initialized CoinbaseClient from coinbase_advanced_py.")
            except TypeError as te:
                logger.warning("[NIJA] CoinbaseClient constructor TypeError: %s", te)
                # Try other common signatures (no kw passphrase, positional, etc.)
                try:
                    client = CoinbaseClient(COINBASE_API_KEY)
                    logger.info("[NIJA] Initialized CoinbaseClient (positional api_key).")
                except Exception as e:
                    logger.warning("[NIJA] Failed alternate CoinbaseClient constructor: %s", e)
                    client = None
        else:
            logger.warning("[NIJA] CoinbaseClient class not located in coinbase_advanced_py.")
            client = None
    except Exception as e:
        logger.exception("[NIJA] Exception while trying to init CoinbaseClient: %s", e)
        client = None

# If RESTClient detected, try it (some coinbase SDKs use this)
if client is None and rest_client is not None:
    try:
        # Many REST client implementations accept key + secret path or key+secret
        kwargs = {}
        if COINBASE_API_KEY:
            kwargs["key"] = COINBASE_API_KEY
        if os.path.exists(COINBASE_PEM_PATH):
            kwargs["secret_path"] = COINBASE_PEM_PATH
        # Avoid unsupported args (like passphrase) — pass minimal set
        client = rest_client(**kwargs)
        logger.info("[NIJA] Initialized RESTClient (coinbase.rest).")
    except TypeError as te:
        logger.warning("[NIJA] RESTClient ctor TypeError (dropping unknown kwargs): %s", te)
        # try minimal
        try:
            client = rest_client(COINBASE_API_KEY)
            logger.info("[NIJA] Initialized RESTClient (positional api_key).")
        except Exception as e:
            logger.warning("[NIJA] Could not init RESTClient: %s", e)
            client = None
    except Exception as e:
        logger.exception("[NIJA] Exception while initializing RESTClient: %s", e)
        client = None

# Final fallback
if client is None:
    logger.warning("[NIJA] No live Coinbase client available — falling back to DummyClient.")
    client = DummyClient()

# --- Helper wrappers for app usage ---
def get_accounts():
    try:
        return client.get_accounts()
    except Exception as e:
        logger.exception("[NIJA] get_accounts failed: %s", e)
        return []

def place_order(*args, **kwargs):
    try:
        return client.place_order(*args, **kwargs)
    except Exception as e:
        logger.exception("[NIJA] place_order failed: %s", e)
        return {"status": "error", "error": str(e)}

def check_live_status() -> bool:
    """Return True if we appear to have a live Coinbase client (not Dummy)."""
    is_dummy = client.__class__.__name__.lower().startswith("dummy")
    if is_dummy:
        logger.warning("[NIJA] Trading not live (DummyClient active)")
        return False
    try:
        accounts = get_accounts()
        if accounts:
            logger.info("[NIJA] ✅ Live trading ready")
            return True
        return False
    except Exception:
        return False

# If imported as script, run a quick startup check
if __name__ == "__main__":
    logger.info("=== NIJA CLIENT STARTUP CHECK ===")
    logger.info("Client class: %s", client.__class__.__name__)
    logger.info("Live check result: %s", check_live_status())
