# /app/nija_client.py
import os
import logging
import importlib
from typing import Optional

logging.basicConfig(level=logging.INFO, format="%(Y-%m-%d %H:%M:%S,) | %(levelname)s | %(message)s")
logger = logging.getLogger("nija_client")

# Candidate module/submodule names we will try (no installs).
IMPORT_CANDIDATES = [
    "coinbase_advanced.client",
    "coinbase_advanced_py.client",
    "coinbase_advanced_py",
    "coinbase_advanced",
    "coinbaseadvanced.client",
    "coinbaseadvanced",
]

CLIENT_ATTR_NAMES = ("Client", "RESTClient", "APIClient")

def find_client_class() -> Optional[type]:
    """
    Try to import likely modules and return the first matching Client-like class.
    Does not install anything — only inspects the runtime.
    """
    for candidate in IMPORT_CANDIDATES:
        try:
            logger.info(f"Trying import candidate: {candidate}")
            # Import module (full path or package)
            mod = importlib.import_module(candidate)
            logger.info(f"Imported module candidate: {mod.__name__}")
            # Prefer direct attributes first
            for attr in CLIENT_ATTR_NAMES:
                if hasattr(mod, attr):
                    cls = getattr(mod, attr)
                    logger.info(f"Found client attr '{attr}' in {mod.__name__}")
                    return cls
            # If module is a package, try its submodules if available
            # (some packages put classes in .client submodule)
            if candidate.endswith(".client") is False:
                try:
                    subname = f"{candidate}.client"
                    sub = importlib.import_module(subname)
                    logger.info(f"Also imported submodule: {subname}")
                    for attr in CLIENT_ATTR_NAMES:
                        if hasattr(sub, attr):
                            cls = getattr(sub, attr)
                            logger.info(f"Found client attr '{attr}' in {subname}")
                            return cls
                except ModuleNotFoundError:
                    pass
        except ModuleNotFoundError:
            logger.debug(f"Candidate not found: {candidate}")
            continue
        except Exception as e:
            logger.warning(f"Import attempt for {candidate} raised: {e}")
            continue
    return None

def test_coinbase_connection() -> bool:
    """
    Returns True only if a Client class can be found and instantiated and
    a safe read-only call can be made (if present).
    """
    client_cls = find_client_class()
    if not client_cls:
        logger.warning("coinbase client not found. Live trading disabled.")
        return False

    # Ensure env vars exist (we won't print secrets)
    api_key = os.environ.get("COINBASE_API_KEY")
    api_secret = os.environ.get("COINBASE_API_SECRET")
    api_sub = os.environ.get("COINBASE_API_SUB")

    if not (api_key and api_secret):
        logger.warning("Missing COINBASE_API_KEY or COINBASE_API_SECRET; connection test disabled.")
        # We still return True if client class exists so container can boot,
        # but we report inability to run live trades elsewhere.
        return False

    try:
        # Try common constructor signatures safely
        try:
            client = client_cls(api_key=api_key, api_secret=api_secret, api_sub=api_sub)
        except TypeError:
            client = client_cls(api_key, api_secret, api_sub)
        # Try common read-only method names but ignore exceptions
        for fn in ("get_accounts", "list_accounts", "accounts", "list"):
            if hasattr(client, fn):
                try:
                    getattr(client, fn)()
                    logger.info("Coinbase client call succeeded; connection OK.")
                    return True
                except Exception as e:
                    logger.warning(f"Read-call {fn} raised: {e}")
        # If constructed but no read-call succeeded, still treat as failure for safety
        logger.warning("Coinbase client instantiated but could not confirm read access.")
        return False
    except Exception as e:
        logger.error(f"Failed to instantiate client class: {e}")
        return False

# For import-time quick debug (used by web/wsgi debug endpoint)
def debug_info() -> dict:
    info = {"import_candidates_checked": [], "env": {}}
    for c in IMPORT_CANDIDATES:
        try:
            spec = importlib.util.find_spec(c)
            spec_info = None
            if spec:
                spec_info = {"name": spec.name, "origin": getattr(spec, "origin", None)}
            info["import_candidates_checked"].append({c: spec_info})
        except Exception as e:
            info["import_candidates_checked"].append({c: f"error: {e}"})
    info["env"]["COINBASE_API_KEY_SET"] = bool(os.environ.get("COINBASE_API_KEY"))
    info["env"]["COINBASE_API_SECRET_SET"] = bool(os.environ.get("COINBASE_API_SECRET"))
    info["env"]["COINBASE_API_SUB_SET"] = bool(os.environ.get("COINBASE_API_SUB"))
    info["coinbase_test"] = test_coinbase_connection()
    return info

if __name__ == "__main__":
    # allow manual run in the container image (no terminal needed; logs appear in deploy logs)
    logger.info("Running nija_client self-test...")
    ok = test_coinbase_connection()
    logger.info(f"coinbase_ok = {ok}")
