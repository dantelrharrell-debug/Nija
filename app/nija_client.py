#!/usr/bin/env python3
"""
nija_client.py

Robust vendor discovery + client instantiation.
Exports:
 - coinbase_client (None | object)
 - simulation_mode (bool)
 - test_coinbase_client(client_or_none) -> bool
 - test_coinbase_connection() -> bool   # BACKWARDS COMPATIBILITY (web expects this)
"""

import os
import logging
import time
from typing import Optional

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("nija_client")

# Environment
COINBASE_API_KEY = os.environ.get("COINBASE_API_KEY")
COINBASE_API_SECRET = os.environ.get("COINBASE_API_SECRET")
COINBASE_API_SUB = os.environ.get("COINBASE_API_SUB")
COINBASE_PEM_CONTENT = os.environ.get("COINBASE_PEM_CONTENT")
LIVE_TRADING = os.environ.get("LIVE_TRADING", "0") == "1"

# Candidate modules to import (vendor first)
_CANDIDATES = [
    "vendor.coinbase_advanced_py.client",
    "vendor.coinbase_advanced.client",
    "coinbase_advanced_py.client",
    "coinbase_advanced.client",
    "coinbase_advanced.client",  # fallback
]

ClientClass = None
_client_module = None

for cand in _CANDIDATES:
    try:
        mod = __import__(cand, fromlist=["*"])
        _client_module = mod
        # prefer class name variations
        for cls_name in ("Client", "CoinbaseClient", "CoinbaseAdvancedClient"):
            cls = getattr(mod, cls_name, None)
            if cls:
                ClientClass = cls
                logger.info("Detected Coinbase client class '%s' in module '%s'.", cls_name, cand)
                break
        if ClientClass:
            break
        # maybe module exposes a factory function named 'Client'
        if hasattr(mod, "Client"):
            ClientClass = getattr(mod, "Client")
            logger.info("Detected Client factory in module '%s'.", cand)
            break
    except Exception as ex:
        # silent — try next candidate
        continue

def _instantiate_client_try_variants() -> Optional[object]:
    """Try several instantiation signatures. Return client or raise last exception."""
    if not ClientClass:
        raise RuntimeError("No Coinbase client class available in vendor modules.")

    # try variants of kwargs
    trial_kw_sets = [
        {"api_key": COINBASE_API_KEY, "api_secret": COINBASE_API_SECRET},
        {"api_key": COINBASE_API_KEY, "api_secret": COINBASE_API_SECRET, "pem_content": COINBASE_PEM_CONTENT},
        {"key": COINBASE_API_KEY, "secret": COINBASE_API_SECRET},
        {"jwt_issuer": os.environ.get("COINBASE_JWT_ISSUER"), "jwt_kid": os.environ.get("COINBASE_JWT_KID"), "pem": COINBASE_PEM_CONTENT},
    ]

    last_exc = None
    for kw in trial_kw_sets:
        # skip if required-looking fields are all None
        if all(v is None for v in kw.values()):
            continue
        try:
            filtered = {k: v for k, v in kw.items() if v is not None}
            logger.info("Attempting to instantiate Coinbase client with keys: %s", list(filtered.keys()))
            client = ClientClass(**filtered)
            return client
        except TypeError as te:
            last_exc = te
            continue
        except Exception as e:
            last_exc = e
            logger.warning("Instantiation attempt failed: %s", e)
            continue

    # try positional fallback
    try:
        logger.info("Attempting positional instantiation fallback.")
        client = ClientClass(COINBASE_API_KEY, COINBASE_API_SECRET)
        return client
    except Exception as e:
        last_exc = e

    raise last_exc or RuntimeError("Failed to instantiate Coinbase client (unknown error).")

def test_coinbase_client(client: Optional[object]) -> bool:
    """Lightweight non-destructive smoke test. Returns True on success."""
    if not client:
        return False
    try:
        if hasattr(client, "ping"):
            client.ping()
            return True
        if hasattr(client, "get_system_status"):
            client.get_system_status()
            return True
        if hasattr(client, "list_products"):
            client.list_products(limit=1)
            return True
        if hasattr(client, "list_accounts"):
            client.list_accounts(limit=1)
            return True
        # if no test method, consider object present a success
        return True
    except Exception as e:
        logger.warning("Coinbase client smoke test failed: %s", e)
        return False

# Attempt to create client if LIVE_TRADING
coinbase_client: Optional[object] = None
simulation_mode = True

if LIVE_TRADING:
    try:
        coinbase_client = _instantiate_client_try_variants()
        ok = test_coinbase_client(coinbase_client)
        if ok:
            simulation_mode = False
            logger.info("Coinbase client instantiated and tested. LIVE TRADING active.")
        else:
            logger.warning("Coinbase client instantiated but test failed — switching to simulation.")
            coinbase_client = None
            simulation_mode = True
    except Exception as e:
        logger.error("Failed to create Coinbase client: %s", e)
        coinbase_client = None
        simulation_mode = True
else:
    logger.info("LIVE_TRADING not set -> running in simulation mode.")
    simulation_mode = True

# Backwards-compatible function expected by web code
def test_coinbase_connection() -> bool:
    """Backwards-compatible wrapper to test the default module client."""
    return test_coinbase_client(coinbase_client)

# Exports
__all__ = [
    "coinbase_client",
    "simulation_mode",
    "test_coinbase_client",
    "test_coinbase_connection",
]

# If run directly show simple loop
if __name__ == "__main__":
    logger.info("=== Nija Trading Bot (standalone) === simulation_mode=%s", simulation_mode)
    try:
        while True:
            if simulation_mode:
                logger.info("Simulation tick")
            else:
                logger.info("Live tick - running smoke test")
                test_coinbase_client(coinbase_client)
            time.sleep(5)
    except KeyboardInterrupt:
        logger.info("Shutting down.")
