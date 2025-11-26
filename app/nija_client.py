# /app/nija_client.py
import importlib
import logging
import os
from typing import Optional, Type

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")

CANDIDATES = [
    "coinbase_advanced",            # official package name (common)
    "coinbase_advanced.client",     # module form
    "coinbase_advanced_py",         # your local copy (older name we used)
    "coinbase_advanced_py.client",
    "coinbase_advanced_py.client.Client",
]

def find_client_class() -> Optional[Type]:
    """Try to import multiple candidates and return the first found Client class."""
    logger.info("Searching for Coinbase client among candidates...")
    tried = []
    for candidate in CANDIDATES:
        try:
            if candidate.endswith(".Client"):
                module_name = candidate.rsplit(".", 1)[0]
                mod = importlib.import_module(module_name)
                cls = getattr(mod, "Client", None)
            elif "." in candidate:
                mod = importlib.import_module(candidate)
                cls = getattr(mod, "Client", None)
            else:
                mod = importlib.import_module(candidate)
                cls = getattr(mod, "Client", None)
            tried.append(candidate)
            if cls:
                logger.info("Found Client in %s", candidate)
                return cls
            else:
                logger.info("Imported %s but no Client attribute found.", candidate)
        except Exception as e:
            logger.debug("Candidate %s import failed: %s", candidate, e)
    logger.warning("Tried candidates: %s", tried)
    return None


def test_coinbase_connection():
    """Attempt a lightweight connection using a found Client class (non-blocking)."""
    logger.info("Testing Coinbase connection...")
    ClientClass = find_client_class()
    if not ClientClass:
        logger.warning("No client class available for connection test.")
        return False

    # load credentials (do not print)
    api_key = os.environ.get("COINBASE_API_KEY")
    api_secret = os.environ.get("COINBASE_API_SECRET")
    api_sub = os.environ.get("COINBASE_API_SUB")

    try:
        client = ClientClass(api_key=api_key, api_secret=api_secret, api_sub=api_sub)
    except Exception as e:
        logger.warning("Failed to initialize Coinbase client: %s", e)
        return False

    # safe fake check: try to call method that most clients have
    for method in ("get_accounts", "list_accounts"):
        try:
            fn = getattr(client, method, None)
            if callable(fn):
                accounts = fn()
                logger.info("Coinbase test successful (method %s returned %s)", method, type(accounts))
                return True
        except Exception as e:
            logger.debug("Method %s on client failed: %s", method, e)

    logger.warning("Client initialized but account listing calls failed.")
    return False


if __name__ == "__main__":
    # When run directly under Python, perform the test and exit
    ok = test_coinbase_connection()
    logger.info("Coinbase test result: %s", "success" if ok else "failure")
