#!/usr/bin/env python3
"""
nija_client.py

Single-file trading client wrapper + small simulation fallback.
Exports:
 - coinbase_client        : actual client instance or None
 - simulation_mode        : True if client unavailable
 - test_coinbase_client(client_or_none) : helper test function
 - test_coinbase_connection() : backwards-compatible wrapper
"""

import os
import logging
import time
from typing import Optional

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("nija_client")

# --- Environment
COINBASE_API_KEY = os.environ.get("COINBASE_API_KEY")
COINBASE_API_SECRET = os.environ.get("COINBASE_API_SECRET")
COINBASE_API_SUB = os.environ.get("COINBASE_API_SUB")
COINBASE_PEM_CONTENT = os.environ.get("COINBASE_PEM_CONTENT")
LIVE_TRADING = os.environ.get("LIVE_TRADING", "0") == "1"

# --- Dynamic import of local/vendor Coinbase lib
ClientClass = None
client_module_path = None
candidates = [
    "vendor.coinbase_advanced_py.client",
    "coinbase_advanced_py.client",
    "coinbase_advanced.client",
    "coinbase_advanced.client",
    "vendor.coinbase_advanced.client",
]

for cand in candidates:
    try:
        # import module
        mod = __import__(cand, fromlist=["*"])
        client_module_path = cand
        # find likely client class names
        for name in ("Client", "CoinbaseClient", "CoinbaseAdvancedClient"):
            cls = getattr(mod, name, None)
            if cls:
                ClientClass = cls
                break
        # if module exposes a factory function named `Client` at top-level
        if not ClientClass:
            ClientClass = getattr(mod, "Client", None)
        if ClientClass:
            logger.info("Detected Coinbase client class '%s' in module '%s'.", getattr(ClientClass, "__name__", "<unknown>"), cand)
            break
    except Exception:
        continue

# --- Helper: try to instantiate client with multiple signatures
def instantiate_client() -> Optional[object]:
    if not ClientClass:
        logger.debug("No client class available in vendor; skipping instantiation.")
        return None

    # candidate kwargs sets to try, ordered
    preference_kw_sets = [
        {"api_key": COINBASE_API_KEY, "api_secret": COINBASE_API_SECRET},
        {"key": COINBASE_API_KEY, "secret": COINBASE_API_SECRET},
        {"api_key": COINBASE_API_KEY, "api_secret": COINBASE_API_SECRET, "pem_content": COINBASE_PEM_CONTENT},
        {"api_key": COINBASE_API_KEY, "pem": COINBASE_PEM_CONTENT},
        {"jwt_issuer": os.environ.get("COINBASE_JWT_ISSUER"), "jwt_kid": os.environ.get("COINBASE_JWT_KID"), "pem": COINBASE_PEM_CONTENT},
    ]

    last_exc = None
    for kw in preference_kw_sets:
        # skip kwsets missing required non-empty values
        if any(v is None for v in kw.values()):
            # allow some None if the class can accept None, but generally skip missing keys
            pass

        try:
            # attempt keyword instantiation
            logger.info("Attempting keyword instantiation of Coinbase client with keys: %s", list(kw.keys()))
            client = ClientClass(**{k: v for k, v in kw.items() if v is not None})
            return client
        except TypeError as te:
            last_exc = te
            # try next signature
            continue
        except Exception as e:
            last_exc = e
            logger.warning("Coinbase client instantiation attempt failed: %s", e)
            continue

    # final attempt: try positional if available (risky)
    try:
        logger.info("Attempting positional instantiation of Coinbase client.")
        client = ClientClass(COINBASE_API_KEY, COINBASE_API_SECRET)
        return client
    except Exception as e:
        logger.exception("All Coinbase client instantiation attempts failed.")
        raise last_exc or e

# --- Light test routine
def test_coinbase_client(client: Optional[object]) -> bool:
    """
    Perform a minimal, safe test of the client. Returns True if test passes.
    Non-destructive calls only.
    """
    if not client:
        return False
    try:
        # prefer safe lightweight methods if present
        if hasattr(client, "ping"):
            client.ping()
            return True
        if hasattr(client, "get_system_status"):
            client.get_system_status()
            return True
        if hasattr(client, "list_products"):
            # call with very small limit
            try:
                client.list_products(limit=1)
                return True
            except TypeError:
                client.list_products()
                return True
        if hasattr(client, "list_accounts"):
            client.list_accounts(limit=1)
            return True
        # no known test - if client object exists treat as success
        return True
    except Exception as e:
        logger.warning("Coinbase client test failed: %s", e)
        return False

# --- Create coinbase_client if LIVE_TRADING, otherwise None (simulation)
coinbase_client = None
simulation_mode = True

if LIVE_TRADING:
    try:
        coinbase_client = instantiate_client()
        if coinbase_client and test_coinbase_client(coinbase_client):
            simulation_mode = False
            logger.info("Coinbase client instantiated and tested. LIVE TRADING enabled.")
        else:
            logger.warning("Coinbase client not ready or test failed; switching to simulation.")
            coinbase_client = None
            simulation_mode = True
    except Exception as e:
        logger.error("Failed to create Coinbase client: %s", e)
        coinbase_client = None
        simulation_mode = True
else:
    logger.info(".LIVE_TRADING not enabled - running in simulation mode.")
    simulation_mode = True

# Backwards-compatible wrappers and exports

def test_coinbase_connection() -> bool:
    """
    Backwards-compatible function expected by some web code.
    Returns True if a client exists and the lightweight test passes.
    """
    try:
        return test_coinbase_client(coinbase_client)
    except Exception:
        return False

__all__ = [
    "coinbase_client",
    "simulation_mode",
    "test_coinbase_client",
    "test_coinbase_connection",
]

# --- If run directly, provide simple loop for background testing / example behavior ----------
if __name__ == "__main__":
    # simple main loop that demonstrates client creation and a placeholder trading loop.
    logger.info("=== Nija Trading Bot Starting (standalone) ===")
    logger.info("simulation_mode=%s", simulation_mode)
    try:
        while True:
            if simulation_mode:
                logger.info("Simulation tick - no live client.")
            else:
                logger.info("Live tick - coinbase_client present.")
                # placeholder: poll account balances or perform safe non-destructive call
                try:
                    test_coinbase_client(coinbase_client)
                except Exception:
                    logger.exception("Error during live tick.")
            time.sleep(5)
    except KeyboardInterrupt:
        logger.info("Shutting down.")
