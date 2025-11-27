#!/usr/bin/env python3
"""
nija_client.py

- No heavy side-effects at import time.
- Exposes:
    create_coinbase_client() -> client or raises
    test_coinbase_connection() -> bool  # safe for import by web workers
    start_trading_loop() -> runs loop (blocking)
"""

import os
import logging
import time
from typing import Optional

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=LOG_LEVEL, format="%(asctime)s | %(levelname)s | %(message)s")
logger = logging.getLogger("nija_client")

# Environment (read at import; values can be updated by container env)
COINBASE_API_KEY = os.environ.get("COINBASE_API_KEY")
COINBASE_API_SECRET = os.environ.get("COINBASE_API_SECRET")
COINBASE_API_SUB = os.environ.get("COINBASE_API_SUB")
COINBASE_PEM_CONTENT = os.environ.get("COINBASE_PEM_CONTENT")
LIVE_TRADING = os.environ.get("LIVE_TRADING", "0") == "1"

# Candidate import modules (prefer vendor path)
_CANDIDATES = [
    "vendor.coinbase_advanced_py.client",
    "vendor.coinbase_advanced.client",
    "coinbase_advanced_py.client",
    "coinbase_advanced.client",
]

def _discover_client_class():
    """Try to find a usable client class/factory in candidate modules.
    Returns (module, ClientClass) or (None, None).
    """
    for cand in _CANDIDATES:
        try:
            mod = __import__(cand, fromlist=["*"])
        except Exception:
            continue
        # look for common class or factory names
        for name in ("Client", "CoinbaseClient", "CoinbaseAdvancedClient"):
            cls = getattr(mod, name, None)
            if cls:
                logger.info("Detected Coinbase client class '%s' in module '%s'.", name, cand)
                return mod, cls
        # sometimes module itself is the factory
        if callable(getattr(mod, "Client", None)):
            logger.info("Detected callable Client in module '%s'.", cand)
            return mod, getattr(mod, "Client")
    return None, None

def create_coinbase_client() -> object:
    """Instantiate Coinbase client. Raises on failure."""
    mod, ClientClass = _discover_client_class()
    if ClientClass is None:
        raise RuntimeError("coinbase client class not found in vendor modules.")

    # try multiple common constructor signatures
    trials = [
        {"api_key": COINBASE_API_KEY, "api_secret": COINBASE_API_SECRET},
        {"api_key": COINBASE_API_KEY, "api_secret": COINBASE_API_SECRET, "pem_content": COINBASE_PEM_CONTENT},
        {"key": COINBASE_API_KEY, "secret": COINBASE_API_SECRET},
        {"jwt_issuer": os.environ.get("COINBASE_JWT_ISSUER"), "jwt_kid": os.environ.get("COINBASE_JWT_KID"), "pem": COINBASE_PEM_CONTENT},
    ]

    last_exc = None
    for kw in trials:
        # filter out missing values
        kw = {k: v for k, v in kw.items() if v is not None}
        if not kw:
            continue
        try:
            logger.info("Attempting to instantiate Coinbase client with keys: %s", list(kw.keys()))
            client = ClientClass(**kw)
            logger.info("Coinbase client instantiated using keys: %s", list(kw.keys()))
            return client
        except TypeError as te:
            last_exc = te
            continue
        except Exception as e:
            last_exc = e
            logger.warning("Instantiation attempt failed: %s", e)
            continue

    # positional fallback
    try:
        logger.info("Attempting positional instantiation fallback.")
        client = ClientClass(COINBASE_API_KEY, COINBASE_API_SECRET)
        return client
    except Exception as e:
        last_exc = e

    raise RuntimeError(f"Failed to instantiate Coinbase client: {last_exc}")

def _smoke_test_client(client: object) -> bool:
    """Non-destructive smoke test of client. Returns True on success."""
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
        # If no test method available, treat instantiation as success
        return True
    except Exception as e:
        logger.warning("Coinbase client smoke test failed: %s", e)
        return False

def test_coinbase_connection() -> bool:
    """Backwards-compatible function. Attempts a temporary client instantiation and test.
    This is safe for web health checks (non-blocking, short).
    """
    try:
        client = create_coinbase_client()
        ok = _smoke_test_client(client)
        return bool(ok)
    except Exception as e:
        logger.debug("test_coinbase_connection: failed: %s", e)
        return False

def start_trading_loop(poll_seconds: int = 5):
    """Blocking trading loop. Instantiate client here (so import is side-effect free)."""
    logger.info("Starting trading loop (LIVE_TRADING=%s)", LIVE_TRADING)
    client = None
    simulation = True

    if LIVE_TRADING:
        try:
            client = create_coinbase_client()
            if _smoke_test_client(client):
                simulation = False
                logger.info("Coinbase client ready (LIVE TRADING).")
            else:
                logger.warning("Coinbase client smoke test failed; falling back to simulation mode.")
                client = None
                simulation = True
        except Exception as e:
            logger.error("Failed to create Coinbase client: %s", e)
            simulation = True
            client = None
    else:
        logger.info("LIVE_TRADING not enabled; running in simulation mode.")

    logger.info("Trading loop started. Simulation mode=%s", simulation)
    try:
        while True:
            if simulation:
                logger.debug("Simulation tick")
            else:
                # Place non-destructive status call to confirm connectivity
                try:
                    _smoke_test_client(client)
                except Exception as e:
                    logger.warning("Live tick error: %s", e)
            time.sleep(poll_seconds)
    except KeyboardInterrupt:
        logger.info("Trading loop shutdown requested.")

# Exported names
__all__ = [
    "create_coinbase_client",
    "test_coinbase_connection",
    "start_trading_loop",
]
