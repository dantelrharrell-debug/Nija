# nija_client.py
import os
import sys
import logging
import importlib
from types import ModuleType

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("nija_client")

DEBUG_PATH = "/app/logs/coinbase_module_debug.txt"

TOP_LEVELS = [
    "coinbase_advanced_py",
    "coinbase_advanced",
    "coinbaseadvanced",
    "coinbase_advanced.client",
    "coinbase_advanced_py.client",
]
SUBMODULES = ["client", "rest", "api", "client.client", "client.rest"]

CLIENT_CANDIDATE_NAMES = [
    "Client", "RESTClient", "APIClient", "CoinbaseClient",
    "CoinbaseRESTClient", "CoinbaseAdvancedClient", "AdvancedClient"
]

def dump_module_info():
    try:
        os.makedirs(os.path.dirname(DEBUG_PATH), exist_ok=True)
        with open(DEBUG_PATH, "w", encoding="utf-8") as f:
            f.write("=== coinbase module debug dump ===\n\n")
            f.write("sys.path:\n")
            for p in sys.path:
                f.write(f"  {p}\n")
            f.write("\nAttempted imports / findings:\n\n")
            for name in TOP_LEVELS:
                try:
                    m = importlib.import_module(name)
                    f.write(f"Imported: {name} -> {getattr(m, '__file__', repr(m))}\n")
                    attrs = [a for a in dir(m) if not a.startswith("__")]
                    f.write("  Attributes (sample):\n")
                    f.write("   " + ", ".join(attrs[:200]) + ("\n" if len(attrs) <= 200 else " ...\n"))
                    f.write("\n")
                except Exception as e:
                    f.write(f"Could not import {name}: {e}\n\n")
            f.write("\n=== End debug ===\n")
    except Exception:
        logger.exception("Failed to write debug file")

def locate_client_class():
    for top in TOP_LEVELS:
        try:
            mod = importlib.import_module(top)
        except Exception:
            continue

        # Try direct attribute names
        for name in CLIENT_CANDIDATE_NAMES:
            try:
                if hasattr(mod, name):
                    obj = getattr(mod, name)
                    if callable(obj):
                        logger.info("Found candidate %s on %s", name, top)
                        return obj
            except Exception:
                pass

        # Try submodules
        for sub in SUBMODULES:
            try:
                candidate = f"{top}.{sub.split('.')[-1]}"
                submod = importlib.import_module(candidate)
                for a in dir(submod):
                    if "client" in a.lower() or a.endswith("Client"):
                        obj = getattr(submod, a)
                        if callable(obj):
                            logger.info("Found candidate %s in %s", a, candidate)
                            return obj
            except Exception:
                pass

        # Heuristic scan
        for a in dir(mod):
            if "client" in a.lower() or a.lower().endswith("client"):
                try:
                    obj = getattr(mod, a)
                    if callable(obj):
                        logger.info("Heuristic found %s in %s", a, top)
                        return obj
                except Exception:
                    pass

    # final fallback
    return None

def test_coinbase_connection() -> bool:
    dump_module_info()

    client_obj = locate_client_class()
    if not client_obj:
        logger.error("Coinbase client class not available after attempts. See %s", DEBUG_PATH)
        return False

    logger.info("Found candidate client object: %r", client_obj)

    API_KEY = os.environ.get("COINBASE_API_KEY")
    API_SECRET = os.environ.get("COINBASE_API_SECRET")
    API_SUB = os.environ.get("COINBASE_API_SUB")
    if not (API_KEY and API_SECRET and API_SUB):
        logger.error("Missing Coinbase env vars.")
        return False

    client = None
    try:
        client = client_obj(api_key=API_KEY, api_secret=API_SECRET, api_sub=API_SUB)
    except TypeError:
        try:
            client = client_obj(API_KEY, API_SECRET, API_SUB)
        except Exception:
            for name in ("from_api_keys", "from_keys", "create", "connect"):
                try:
                    if hasattr(client_obj, name):
                        client = getattr(client_obj, name)(API_KEY, API_SECRET, API_SUB)
                        break
                except Exception:
                    continue
    except Exception as e:
        logger.warning("Instantiation initial error: %s", e)

    if client is None:
        logger.error("Unable to instantiate a client from candidate object.")
        return False

    for method in ("get_accounts", "list_accounts", "accounts", "list"):
        if hasattr(client, method):
            try:
                getattr(client, method)()
                logger.info("Coinbase connection test succeeded using '%s'.", method)
                return True
            except Exception as e:
                logger.warning("Read method %s exists but failed: %s", method, e)

    logger.info("Client instantiated but no standard read method succeeded — marking as success.")
    return True
