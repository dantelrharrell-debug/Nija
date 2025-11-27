import os
import logging

# -----------------------
# Logging configuration
# -----------------------
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

# -----------------------
# Dynamic Coinbase client import
# -----------------------
Client = None
IMPORT_MODULE = None

candidates = [
    "coinbase_advanced.client",
    "coinbase_advanced_py.client",
    "coinbase_advanced",
    "coinbase_advanced_py",
]

for cand in candidates:
    try:
        parts = cand.split(".")
        if len(parts) == 2:
            modname, attr = parts
            mod = __import__(modname, fromlist=[attr])
            maybe = getattr(mod, attr, None)
            if maybe:
                Client = maybe
                IMPORT_MODULE = cand
                break
        else:
            mod = __import__(cand)
            Client = getattr(mod, "Client", None) or getattr(mod, "client", None)
            if Client:
                IMPORT_MODULE = cand
                break
    except Exception:
        continue

COINBASE_CLIENT_AVAILABLE = Client is not None
if COINBASE_CLIENT_AVAILABLE:
    logger.info("Coinbase client import succeeded via '%s'.", IMPORT_MODULE)
else:
    logger.warning("Coinbase client import failed for all candidates: %s", candidates)

# -----------------------
# Test Coinbase connection
# -----------------------
def test_coinbase_connection() -> bool:
    """Return True if a light Coinbase client test succeeds."""
    if not COINBASE_CLIENT_AVAILABLE:
        logger.warning("No Coinbase client available for connection test.")
        return False

    api_key = os.environ.get("COINBASE_API_KEY")
    api_secret = os.environ.get("COINBASE_API_SECRET")
    api_sub = os.environ.get("COINBASE_API_SUB")

    if not api_key or not api_secret:
        logger.warning("Coinbase API credentials missing from environment.")
        return False

    try:
        try:
            client = Client(api_key=api_key, api_secret=api_secret, api_sub=api_sub)
        except TypeError:
            # Try alternative class-based Client instantiation
            module_root = IMPORT_MODULE.split(".")[0] if IMPORT_MODULE else None
            if module_root:
                mod = __import__(module_root, fromlist=["Client"])
                client_cls = getattr(mod, "Client", None)
                if client_cls:
                    client = client_cls(api_key=api_key, api_secret=api_secret, api_sub=api_sub)
                else:
                    logger.warning("Unable to instantiate Coinbase client (no Client class found).")
                    return False
            else:
                logger.warning("Unable to instantiate Coinbase client (signature mismatch).")
                return False

        # Minimal test calls
        if hasattr(client, "ping"):
            client.ping()
        elif hasattr(client, "get_system_status"):
            client.get_system_status()
        elif hasattr(client, "list_products"):
            client.list_products(limit=1)
        elif hasattr(client, "list_accounts"):
            client.list_accounts(limit=1)
        else:
            logger.info("Coinbase client instantiated; no test call available.")
            return True

        logger.info("Coinbase connection test: success")
        return True
    except Exception as ex:
        logger.warning("Coinbase connection test failed: %s", ex)
        return False
