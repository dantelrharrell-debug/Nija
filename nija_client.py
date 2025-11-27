# nija_client.py
import os
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

Client = None
IMPORT_MODULE = None

# Common candidate import roots — extend if you discover another variant
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
            mod = __import__(cand, fromlist=["Client", "client"])
            maybe = getattr(mod, "Client", None) or getattr(mod, "client", None)
            if maybe:
                Client = maybe
                IMPORT_MODULE = cand
                break
    except Exception:
        continue

COINBASE_CLIENT_AVAILABLE = Client is not None
if COINBASE_CLIENT_AVAILABLE:
    logger.info("Coinbase client import succeeded via '%s'.", IMPORT_MODULE)
else:
    logger.warning("Coinbase client import failed for candidates: %s", candidates)


def test_coinbase_connection() -> bool:
    if not COINBASE_CLIENT_AVAILABLE:
        logger.warning("No Coinbase client available for connection test.")
        return False

    api_key = os.environ.get("COINBASE_API_KEY")
    api_secret = os.environ.get("COINBASE_API_SECRET")
    api_sub = os.environ.get("COINBASE_API_SUB")

    if not api_key or not api_secret:
        logger.warning("Coinbase API credentials missing in environment.")
        return False

    try:
        # instantiate (client interfaces vary)
        try:
            client = Client(api_key=api_key, api_secret=api_secret, api_sub=api_sub)
        except TypeError:
            # try to find a Client class in the module root
            module_root = IMPORT_MODULE.split(".")[0] if IMPORT_MODULE else None
            if module_root:
                mod = __import__(module_root, fromlist=["Client"])
                client_cls = getattr(mod, "Client", None)
                if client_cls:
                    client = client_cls(api_key=api_key, api_secret=api_secret, api_sub=api_sub)
                else:
                    logger.warning("No Client class found to instantiate.")
                    return False
            else:
                logger.warning("Unable to instantiate Coinbase client (signature mismatch).")
                return False

        # light test call depending on API available
        if hasattr(client, "ping"):
            client.ping()
        elif hasattr(client, "get_system_status"):
            client.get_system_status()
        elif hasattr(client, "list_products"):
            client.list_products(limit=1)
        elif hasattr(client, "list_accounts"):
            client.list_accounts(limit=1)
        else:
            logger.info("Client instantiated; no known test call — treating as success.")
            return True

        logger.info("Coinbase test call succeeded.")
        return True
    except Exception as e:
        logger.warning("Coinbase connection test failed: %s", e)
        return False
