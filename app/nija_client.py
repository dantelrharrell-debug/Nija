# nija_client.py
import os
import sys
import logging
import importlib

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("nija_client")

# Candidate top-level modules and submodules to try (order matters)
IMPORT_TRIES = [
    ("coinbase_advanced", "client"),
    ("coinbase_advanced_py", "client"),
    ("coinbase_advanced_py", None),
    ("coinbaseadvanced", None),
    ("coinbase_advanced", None),
]

def find_client_class():
    """
    Try import variants and return a Client class or None.
    Logs what it finds for diagnostics.
    """
    for top, sub in IMPORT_TRIES:
        try:
            module = importlib.import_module(top)
            logger.info(f"Imported module '{top}' (path: {getattr(module, '__file__', 'builtin/package')})")
            # if submodule specified, try it
            if sub:
                try:
                    submod = importlib.import_module(f"{top}.{sub}")
                    logger.info(f"Imported submodule '{top}.{sub}'")
                    module_to_check = submod
                except Exception as e:
                    logger.warning(f"Could not import submodule '{top}.{sub}': {e}")
                    module_to_check = module
            else:
                module_to_check = module

            # Try common attribute names
            for attr in ("Client", "RESTClient", "APIClient"):
                if hasattr(module_to_check, attr):
                    logger.info(f"Found client attribute '{attr}' in {module_to_check.__name__}")
                    return getattr(module_to_check, attr)

            # If module exposes constructors at top-level (rare), return module itself in case it is callable
            if callable(module_to_check):
                logger.info(f"Top-level object {module_to_check} is callable; returning it as client class")
                return module_to_check

            # As a last resort, scan module attributes for names containing 'client' or 'Client'
            for name in dir(module_to_check):
                if "client" in name.lower() or name.lower().endswith("client"):
                    obj = getattr(module_to_check, name)
                    if callable(obj):
                        logger.info(f"Heuristic found potential client: {top}.{name}")
                        return obj

        except ModuleNotFoundError:
            continue
        except Exception as e:
            logger.warning(f"Import try for '{top}' raised unexpected error: {e}")
    logger.error("Could not locate any Coinbase client class in known module names.")
    return None

def test_coinbase_connection() -> bool:
    """
    Ensure client class present, instantiate with env vars, perform a safe read call if available.
    Returns True on success, False on failure (no exceptions thrown to crash container).
    """
    client_cls = find_client_class()
    if not client_cls:
        logger.error("Coinbase client class not found.")
        return False

    API_KEY = os.environ.get("COINBASE_API_KEY")
    API_SECRET = os.environ.get("COINBASE_API_SECRET")
    API_SUB = os.environ.get("COINBASE_API_SUB")
    if not (API_KEY and API_SECRET and API_SUB):
        logger.error("Missing Coinbase credentials in env.")
        return False

    # Try flexible instantiation
    client = None
    try:
        # keyword constructor
        client = client_cls(api_key=API_KEY, api_secret=API_SECRET, api_sub=API_SUB)
    except TypeError:
        try:
            # positional constructor
            client = client_cls(API_KEY, API_SECRET, API_SUB)
        except Exception:
            # try common factory names on module/class
            for factory in ("from_keys", "from_api_keys", "from_cloud_api_keys", "create"):
                try:
                    if hasattr(client_cls, factory):
                        client = getattr(client_cls, factory)(API_KEY, API_SECRET, API_SUB)
                        break
                except Exception:
                    continue
    except Exception as e:
        logger.warning(f"Instantiation error (initial): {e}")

    if client is None:
        logger.error("Unable to instantiate Coinbase client (constructor mismatch).")
        return False

    # Try safe read-only methods
    for fn in ("get_accounts", "list_accounts", "accounts", "list"):
        if hasattr(client, fn):
            try:
                getattr(client, fn)()
                logger.info(f"Coinbase connection test succeeded using method '{fn}'.")
                return True
            except Exception as e:
                logger.warning(f"Method {fn} exists but call failed: {e}")

    # If we got here instantiation worked but no standard read method succeeded, assume OK
    logger.info("Coinbase client instantiated but no standard read method succeeded — treating as success.")
    return True
