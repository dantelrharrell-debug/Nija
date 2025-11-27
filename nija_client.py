# nija_client.py
import os
import time
import logging
import inspect

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=LOG_LEVEL, format="%(Y-%m-%d %H:%M:%S,")  # kept intentionally simple
logger = logging.getLogger("nija_client")
logger.setLevel(LOG_LEVEL)

# load env
COINBASE_API_KEY = os.environ.get("COINBASE_API_KEY")
COINBASE_API_SECRET = os.environ.get("COINBASE_API_SECRET")
COINBASE_API_SUB = os.environ.get("COINBASE_API_SUB")
COINBASE_PEM_CONTENT = os.environ.get("COINBASE_PEM_CONTENT")
LIVE_TRADING = os.environ.get("LIVE_TRADING", "0") == "1"
DEFAULT_LOOP_INTERVAL = float(os.environ.get("LOOP_INTERVAL", "5"))

# Try to import vendor client module in several ways
ClientClass = None
CLIENT_MODULE = None
try:
    # preferred when vendor/ is on PYTHONPATH: vendor.coinbase_advanced_py.client
    import vendor.coinbase_advanced_py.client as client_mod
    CLIENT_MODULE = "vendor.coinbase_advanced_py.client"
except Exception:
    client_mod = None

candidates = [
    ("vendor.coinbase_advanced_py.client", "client"),
    ("coinbase_advanced_py.client", "client"),
    ("coinbase_advanced.client", "client"),
    ("coinbase_advanced_py", None),
    ("coinbase_advanced", None),
]

if not client_mod:
    for modname, _ in candidates:
        try:
            client_mod = __import__(modname, fromlist=["*"])
            CLIENT_MODULE = modname
            break
        except Exception:
            client_mod = None
            continue

if client_mod:
    # try to discover a client class (prefer 'Client', 'CoinbaseClient', 'Coinbase')
    for candidate_name in ("Client", "CoinbaseClient", "Coinbase", "CoinbaseAPI"):
        cls = getattr(client_mod, candidate_name, None)
        if inspect.isclass(cls):
            ClientClass = cls
            logger.info("Detected Coinbase client class '%s' in module '%s'.", candidate_name, CLIENT_MODULE)
            break

    # fallback: if module exposes a factory function or object
    if ClientClass is None:
        # if module defines a submodule 'client' with a class
        sub = getattr(client_mod, "client", None)
        if sub:
            for candidate_name in ("Client", "CoinbaseClient"):
                cls = getattr(sub, candidate_name, None)
                if inspect.isclass(cls):
                    ClientClass = cls
                    logger.info("Detected Coinbase client class '%s' in submodule '%s.client'.", candidate_name, CLIENT_MODULE)
                    break

if not ClientClass:
    logger.error("coinbase_advanced client package not found or no usable Client class detected. Bot will run in simulation mode.")
else:
    logger.info("Coinbase client module present: %s", CLIENT_MODULE)

def _instantiate_client():
    """Try multiple constructor signatures and return an instance or raise."""
    if ClientClass is None:
        raise RuntimeError("No Coinbase client class available")

    ctor = ClientClass.__init__
    sig = inspect.signature(ctor)
    # build candidate kwargs according to what we have available
    candidates = []

    # common: api_key + api_secret
    kwargs_kv = {}
    if COINBASE_API_KEY and COINBASE_API_SECRET:
        kwargs_kv = {"api_key": COINBASE_API_KEY, "api_secret": COINBASE_API_SECRET}
        candidates.append(kwargs_kv)

    # some libs call the key 'key'/'secret'
    if COINBASE_API_KEY and COINBASE_API_SECRET:
        candidates.append({"key": COINBASE_API_KEY, "secret": COINBASE_API_SECRET})

    # jwt/pem style
    if COINBASE_PEM_CONTENT:
        candidates.append({"pem_content": COINBASE_PEM_CONTENT})
        candidates.append({"pem": COINBASE_PEM_CONTENT})

    # try adding sub
    if COINBASE_API_SUB:
        # try with api_sub appended to earlier candidates
        new = dict(kwargs_kv)
        new["api_sub"] = COINBASE_API_SUB
        candidates.append(new)

    # unique: COINBASE_API_BASE for alternate endpoints
    if os.environ.get("COINBASE_API_BASE"):
        for c in list(candidates):
            c2 = dict(c)
            c2["api_base"] = os.environ.get("COINBASE_API_BASE")
            candidates.append(c2)

    last_err = None
    for kw in candidates:
        try:
            # instantiate using only matching kwargs from the class signature
            matching = {}
            for k in kw:
                if k in sig.parameters:
                    matching[k] = kw[k]
            # If matching empty, still attempt to pass kw (some clients accept **kwargs)
            if matching:
                inst = ClientClass(**matching)
            else:
                inst = ClientClass(**kw)
            logger.info("Coinbase client instantiated using keys: %s", sorted(list(kw.keys())))
            return inst
        except TypeError as te:
            last_err = te
            # continue to next candidate
        except Exception as ex:
            last_err = ex
    # final attempt: try zero-arg constructor
    try:
        inst = ClientClass()
        logger.info("Coinbase client instantiated with empty constructor.")
        return inst
    except Exception as ex:
        last_err = ex

    raise RuntimeError(f"Failed to instantiate Coinbase client: {last_err}")

# exported helper used by health endpoint
def test_coinbase_connection() -> bool:
    """
    Lightweight test for use in /healthz.
    Attempts to instantiate a client and perform a minimal safe call when available.
    Returns True when call succeeds, False otherwise.
    """
    if ClientClass is None:
        logger.debug("test_coinbase_connection: client class not available")
        return False

    try:
        client = _instantiate_client()
    except Exception as e:
        logger.warning("test_coinbase_connection: failed to instantiate client: %s", e)
        return False

    # minimal read-only test calls (try multiple)
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
        # if none of the above exist treat instantiation success as test pass
        return True
    except Exception as e:
        logger.warning("test_coinbase_connection: call failed: %s", e)
        return False

# Top-level: create a client for the running loop if LIVE_TRADING else None
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

# Minimal example trading loop. Replace with your real logic.
def trading_loop():
    logger.info("Starting trading loop (LIVE_TRADING=%s)", LIVE_TRADING)
    iteration = 0
    while True:
        iteration += 1
        try:
            if coinbase_client:
                # an example safe call or account check
                # adapt to the client's API surface (these names are library-specific)
                if hasattr(coinbase_client, "list_accounts"):
                    try:
                        accounts = coinbase_client.list_accounts(limit=1)
                        logger.debug("Account check OK (iter=%d)", iteration)
                    except Exception:
                        logger.debug("Account check failed (iter=%d)", iteration)
                else:
                    logger.debug("Client present but no account test method found.")
            else:
                logger.debug("Simulation tick: %d", iteration)
            time.sleep(DEFAULT_LOOP_INTERVAL)
        except Exception as ex:
            logger.exception("Trading loop error: %s", ex)
            time.sleep(5)

if __name__ == "__main__":
    logger.info(".env not present — using environment variables provided by the host." if not os.path.exists(".env") else ".env present")
    logger.info("Starting trading loop (LIVE_TRADING=%s)", LIVE_TRADING)
    try:
        trading_loop()
    except KeyboardInterrupt:
        logger.info("Shutting down trading loop (keyboard interrupt).")
