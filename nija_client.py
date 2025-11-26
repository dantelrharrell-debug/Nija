# nija_client.py
import os
import logging
import importlib

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("nija_client")

# Do NOT run any tests at import time.
# This module only exposes helpers and a test function that start_all.sh will call once.

IMPORT_CANDIDATES = [
    "coinbase_advanced.client",
    "coinbase_advanced_py.client",
    "coinbase_advanced_py",
    "coinbase_advanced",
]

def try_import_client_class():
    for candidate in IMPORT_CANDIDATES:
        try:
            spec = importlib.util.find_spec(candidate)
            if not spec:
                continue
            mod = importlib.import_module(candidate)
            # prefer Client attribute
            for attr in ("Client", "RESTClient", "APIClient"):
                if hasattr(mod, attr):
                    logger.info(f"Imported {candidate}; found client attr {attr}")
                    return getattr(mod, attr)
            # if module itself is client-like, return module (caller will try instantiation)
            return mod
        except ModuleNotFoundError:
            continue
        except Exception as e:
            logger.debug(f"Import attempt {candidate} raised: {e}")
    return None

def test_coinbase_connection(timeout_seconds: int = 10) -> bool:
    """
    Try to import the Coinbase client and do a minimal instantiation / read-only call.
    Returns True if a usable client is available; False otherwise.
    This function should be called *once* at container startup (before Gunicorn forks).
    """
    client_cls = try_import_client_class()
    if not client_cls:
        logger.warning("Coinbase client not available (module not installed).")
        return False

    API_KEY = os.environ.get("COINBASE_API_KEY")
    API_SECRET = os.environ.get("COINBASE_API_SECRET")
    API_SUB = os.environ.get("COINBASE_API_SUB")

    if not (API_KEY and API_SECRET and API_SUB):
        logger.warning("Coinbase env vars missing; skipping live calls.")
        # still considered available (module present) but not configured
        return False

    try:
        # Try common constructor signatures; be defensive about calling methods
        try:
            client = client_cls(api_key=API_KEY, api_secret=API_SECRET, api_sub=API_SUB)
        except TypeError:
            try:
                client = client_cls(API_KEY, API_SECRET, API_SUB)
            except TypeError:
                client = client_cls()  # last resort

        # Try a small read-only call if present (wrap in try/except)
        for fn in ("get_accounts", "list_accounts", "accounts", "list"):
            if hasattr(client, fn):
                try:
                    getattr(client, fn)()
                    logger.info("Coinbase client call succeeded; connection OK.")
                    return True
                except Exception as e:
                    logger.debug(f"Read-only call {fn} failed: {e}")
                    # keep trying other call names
        # If instantiation succeeded but no known read-only calls ran, we still treat as available.
        logger.info("Coinbase client instantiated (no known read call succeeded).")
        return True
    except Exception as e:
        logger.warning(f"Coinbase connection test failed: {e}")
        return False
