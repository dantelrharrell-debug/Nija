# nija_client.py
"""
Robust Coinbase client loader + minimal trading loop.
- Detects vendor.coinbase_advanced_py or other coinbase module names
- Tries common client class names and constructor keywords
- Exposes test_coinbase_connection() for health checks
- Runs a safe example trading loop when executed directly
"""

import os
import time
import logging
import inspect

# -----------------------
# Logging configuration (FIXED)
# -----------------------
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
# valid format placeholders: asctime, levelname, message, name, etc.
logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("nija_client")

# -----------------------
# Environment / config
# -----------------------
COINBASE_API_KEY = os.environ.get("COINBASE_API_KEY")
COINBASE_API_SECRET = os.environ.get("COINBASE_API_SECRET")
COINBASE_API_SUB = os.environ.get("COINBASE_API_SUB")
COINBASE_PEM_CONTENT = os.environ.get("COINBASE_PEM_CONTENT")
COINBASE_API_BASE = os.environ.get("COINBASE_API_BASE")  # optional
LIVE_TRADING = os.environ.get("LIVE_TRADING", "0") == "1"
LOOP_INTERVAL = float(os.environ.get("LOOP_INTERVAL", "5"))

# -----------------------
# Try to find the client module/class
# -----------------------
ClientClass = None
CLIENT_MODULE = None
_possible_modules = [
    "vendor.coinbase_advanced_py.client",
    "coinbase_advanced_py.client",
    "coinbase_advanced.client",
    "coinbase_advanced_py",
    "coinbase_advanced",
]

for modname in _possible_modules:
    try:
        mod = __import__(modname, fromlist=["*"])
        CLIENT_MODULE = modname
        # prefer top-level class names
        for candidate in ("Client", "CoinbaseClient", "Coinbase", "CoinbaseAPI"):
            cls = getattr(mod, candidate, None)
            if inspect.isclass(cls):
                ClientClass = cls
                logger.info("Detected Coinbase client class '%s' in module '%s'.", candidate, modname)
                break
        # fallback: sometimes class is inside a .client submodule (when mod is package)
        if ClientClass is None:
            sub = getattr(mod, "client", None)
            if sub:
                for candidate in ("Client", "CoinbaseClient", "Coinbase"):
                    cls = getattr(sub, candidate, None)
                    if inspect.isclass(cls):
                        ClientClass = cls
                        CLIENT_MODULE = modname + ".client"
                        logger.info("Detected Coinbase client class '%s' in submodule '%s.client'.", candidate, modname)
                        break
        if ClientClass:
            break
    except Exception:
        # silent continue: next candidate
        continue

if ClientClass is None:
    logger.warning("No Coinbase client class detected. Bot will run in simulation mode.")

# -----------------------
# Instantiation logic (tries several kwarg signatures)
# -----------------------
def _instantiate_client():
    if ClientClass is None:
        raise RuntimeError("No Coinbase client class available to instantiate")

    sig = inspect.signature(ClientClass.__init__)
    # prepare candidate kw dicts (ordered tries)
    candidates = []

    # common api_key/api_secret
    if COINBASE_API_KEY and COINBASE_API_SECRET:
        candidates.append({"api_key": COINBASE_API_KEY, "api_secret": COINBASE_API_SECRET})
        candidates.append({"key": COINBASE_API_KEY, "secret": COINBASE_API_SECRET})

    # pem/jwt style
    if COINBASE_PEM_CONTENT:
        candidates.append({"pem_content": COINBASE_PEM_CONTENT})
        candidates.append({"pem": COINBASE_PEM_CONTENT})
        candidates.append({"jwt_pem": COINBASE_PEM_CONTENT})

    # optional api_sub
    if COINBASE_API_SUB:
        # append api_sub to previously assembled candidates
        for base in list(candidates):
            c = dict(base)
            c["api_sub"] = COINBASE_API_SUB
            candidates.append(c)

    # optional api_base
    if COINBASE_API_BASE:
        for base in list(candidates):
            c = dict(base)
            c["api_base"] = COINBASE_API_BASE
            candidates.append(c)

    last_exc = None
    for kw in candidates:
        try:
            # only pass matching kwargs to avoid unexpected-kw issues
            filtered = {k: v for k, v in kw.items() if k in sig.parameters}
            if filtered:
                inst = ClientClass(**filtered)
            else:
                # try passing whatever; some libs accept **kwargs
                inst = ClientClass(**kw)
            logger.info("Coinbase client instantiated using keys: %s", sorted(list(kw.keys())))
            return inst
        except TypeError as te:
            last_exc = te
            logger.debug("Constructor signature mismatch with keys %s: %s", list(kw.keys()), te)
            continue
        except Exception as ex:
            last_exc = ex
            logger.debug("Instantiation failed with keys %s: %s", list(kw.keys()), ex)
            continue

    # final fallback: no-arg constructor
    try:
        inst = ClientClass()
        logger.info("Coinbase client instantiated with empty constructor.")
        return inst
    except Exception as ex:
        last_exc = ex

    raise RuntimeError(f"Failed to instantiate Coinbase client: {last_exc}")

# -----------------------
# health test helper (used by web.healthz)
# -----------------------
def test_coinbase_connection() -> bool:
    if ClientClass is None:
        logger.debug("test_coinbase_connection: no client class available")
        return False
    try:
        client = _instantiate_client()
    except Exception as e:
        logger.warning("test_coinbase_connection: instantiate failed: %s", e)
        return False

    # try a safe read-only method if present
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
        # if no test call exists, treat successful instantiation as positive
        return True
    except Exception as ex:
        logger.warning("test_coinbase_connection: api call failed: %s", ex)
        return False

# -----------------------
# create client for runtime if LIVE_TRADING
# -----------------------
coinbase_client = None
try:
    if LIVE_TRADING and ClientClass:
        coinbase_client = _instantiate_client()
        logger.info("Coinbase client ready (LIVE_TRADING=%s).", LIVE_TRADING)
    else:
        logger.info("Coinbase client not created - running in simulation mode.")
except Exception as e:
    logger.error("Failed to create Coinbase client: %s", e)
    coinbase_client = None

# -----------------------
# Minimal trading loop (example)
# -----------------------
def trading_loop():
    logger.info("Starting trading loop (LIVE_TRADING=%s)", LIVE_TRADING)
    tick = 0
    while True:
        tick += 1
        try:
            if coinbase_client:
                # attempt a safe read if supported
                try:
                    if hasattr(coinbase_client, "list_accounts"):
                        _ = coinbase_client.list_accounts(limit=1)
                        logger.debug("Account check OK (tick=%d)", tick)
                    else:
                        logger.debug("Client present but no list_accounts method (tick=%d)", tick)
                except Exception as ex:
                    logger.warning("Account check error: %s", ex)
            else:
                logger.debug("Simulation tick: %d", tick)
            time.sleep(LOOP_INTERVAL)
        except Exception:
            logger.exception("Unhandled exception in trading loop; sleeping briefly and continuing")
            time.sleep(5)

# -----------------------
# CLI entrypoint
# -----------------------
if __name__ == "__main__":
    logger.info(".env present: %s", os.path.exists(".env"))
    logger.info("Starting trading loop (LIVE_TRADING=%s)", LIVE_TRADING)
    try:
        trading_loop()
    except KeyboardInterrupt:
        logger.info("Trading loop interrupted by user, exiting.")
