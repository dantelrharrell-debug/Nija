# nija_client.py
import os
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

Client = None
IMPORT_MODULE = None

# Try the two likely import names used by coinbase libs
candidates = [
    "coinbase_advanced.client",    # repo may expose coinbase_advanced
    "coinbase_advanced_py.client", # some distributions expose coinbase_advanced_py
    "coinbase_advanced",           # fallback module-level
    "coinbase_advanced_py",        # fallback module-level
]

for cand in candidates:
    try:
        # dynamic import
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
            # prefer a 'Client' object or 'client' module inside
            Client = getattr(mod, "Client", None) or getattr(mod, "client", None) or None
            if Client:
                IMPORT_MODULE = cand
                break
    except Exception:
        # keep trying other candidates without noisy trace
        continue

COINBASE_CLIENT_AVAILABLE = Client is not None
if COINBASE_CLIENT_AVAILABLE:
    logger.info("Coinbase client import succeeded via '%s'.", IMPORT_MODULE)
else:
    logger.warning("Coinbase client import failed for all candidates: %s", candidates)


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
        # instantiate client (library signatures vary)
        try:
            client = Client(api_key=api_key, api_secret=api_secret, api_sub=api_sub)
        except TypeError:
            # maybe Client is a module exposing a Client class
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

        # Try minimal safe test calls (library-dependent)
        if hasattr(client, "ping"):
            client.ping()
        elif hasattr(client, "get_system_status"):
            client.get_system_status()
        elif hasattr(client, "list_products"):
            client.list_products(limit=1)
        elif hasattr(client, "list_accounts"):
            client.list_accounts(limit=1)
        else:
            # If instantiation succeeded but no simple test exists, treat as success
            logger.info("Coinbase client instantiated; no test call available.")
            return True

        logger.info("Coinbase connection test: success")
        return True
    except Exception as ex:
        logger.warning("Coinbase connection test failed: %s", ex)
        return False
