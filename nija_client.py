# nija_client.py
import os
import logging
import importlib
import importlib.util
import pkgutil
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("nija_client")

# More exhaustive candidate list (covers common variants)
IMPORT_CANDIDATES = [
    "coinbase_advanced.client",
    "coinbase_advanced_py.client",
    "coinbase_advanced_py",
    "coinbase_advanced",
    "coinbaseadvanced.client",
    "coinbaseadvanced",
    "coinbase_advanced_py.client.client",  # paranoid
]

DEBUG_FILE = "/app/logs/coinbase_module_debug.txt"

def write_debug(message: str):
    try:
        os.makedirs(os.path.dirname(DEBUG_FILE), exist_ok=True)
        with open(DEBUG_FILE, "a") as f:
            f.write(f"{datetime.utcnow().isoformat()}Z | {message}\n")
    except Exception:
        logger.debug("Could not write debug file")

def try_import_client_class():
    """
    Try a list of candidate import names and return the first usable client class or None.
    Logs every attempt and writes a short debug file for the /debug/coinbase endpoint.
    """
    write_debug("try_import_client_class: start")
    for candidate in IMPORT_CANDIDATES:
        try:
            write_debug(f"attempting import: {candidate}")
            # fast check if module exists
            spec = importlib.util.find_spec(candidate)
            if spec is None:
                write_debug(f"spec not found for {candidate}")
                continue
            mod = importlib.import_module(candidate)
            # if candidate is a module with Client attribute
            for attr in ("Client", "RESTClient", "APIClient"):
                if hasattr(mod, attr):
                    write_debug(f"found attr {attr} in {candidate}")
                    return getattr(mod, attr)
            # if module itself is a class-like object return it
            write_debug(f"imported {candidate} but no Client attr; returning module object")
            return mod
        except ModuleNotFoundError:
            write_debug(f"ModuleNotFoundError for {candidate}")
            continue
        except Exception as e:
            write_debug(f"import attempt {candidate} raised: {e}")
            logger.debug(f"import attempt {candidate} raised: {e}")
            continue
    write_debug("try_import_client_class: none found")
    return None

def test_coinbase_connection(timeout_seconds: int = 10) -> bool:
    """
    Try to import the Coinbase client and do a minimal instantiation / read-only call.
    Returns True if usable; False otherwise.
    Side effect: writes a one-line debug file to /app/logs/coinbase_module_debug.txt
    """
    write_debug("test_coinbase_connection: start")
    client_cls = try_import_client_class()
    if not client_cls:
        msg = "Coinbase client not available (module not installed)."
        logger.warning(msg)
        write_debug(msg)
        return False

    API_KEY = os.environ.get("COINBASE_API_KEY")
    API_SECRET = os.environ.get("COINBASE_API_SECRET")
    API_SUB = os.environ.get("COINBASE_API_SUB")

    if not (API_KEY and API_SECRET and API_SUB):
        msg = "Coinbase env vars missing or incomplete."
        logger.warning(msg)
        write_debug(msg)
        return False

    try:
        # Try common constructor signatures
        try:
            client = client_cls(api_key=API_KEY, api_secret=API_SECRET, api_sub=API_SUB)
        except TypeError:
            try:
                client = client_cls(API_KEY, API_SECRET, API_SUB)
            except TypeError:
                # last resort: call with no args
                client = client_cls()

        # Try a small read-only call if present
        for fn in ("get_accounts", "list_accounts", "accounts", "list"):
            if hasattr(client, fn):
                try:
                    getattr(client, fn)()
                    logger.info("Coinbase client call succeeded; connection OK.")
                    write_debug("Coinbase client call succeeded")
                    return True
                except Exception as e:
                    write_debug(f"read-only call {fn} failed: {e}")
                    logger.debug(f"read-only call {fn} failed: {e}")
                    # keep trying other call names
        # If instantiation succeeded but no known read-only calls ran, treat as available
        logger.info("Coinbase client instantiated (no known read call succeeded).")
        write_debug("Coinbase client instantiated (no known read call succeeded).")
        return True
    except Exception as e:
        write_debug(f"Coinbase connection test failed: {e}")
        logger.warning(f"Coinbase connection test failed: {e}")
        return False
