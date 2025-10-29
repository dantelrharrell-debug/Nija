# nija_client.py
import os
import logging
from typing import Any

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_client")

# Config (environment)
API_KEY = os.getenv("COINBASE_API_KEY")
API_SECRET = os.getenv("COINBASE_API_SECRET")                 # raw secret (rare)
API_SECRET_PATH = os.getenv("COINBASE_API_SECRET_PATH")       # path to PEM or key file
PASSPHRASE = os.getenv("COINBASE_PASSPHRASE")
PEM_FALLBACK = "/opt/render/project/secrets/coinbase.pem"     # start.sh writes this if provided

# If user provided COINBASE_API_SECRET (path) or we wrote PEM, prefer that path
if not API_SECRET_PATH and os.path.exists(PEM_FALLBACK):
    API_SECRET_PATH = PEM_FALLBACK

# A flexible wrapper which tries different client import/constructors
client = None
_live = False

def _use_dummy(msg=None):
    global client, _live
    if msg:
        logger.warning(msg)
    class DummyClient:
        def get_accounts(self):
            logger.info("[NIJA-DUMMY] get_accounts called")
            return [{"currency": "USD", "balance": "1000"}]
        def place_order(self, **kwargs):
            logger.info(f"[NIJA-DUMMY] place_order called: {kwargs}")
            return {"id":"dummy_order", "status":"simulated"}
    client = DummyClient()
    _live = False

# Try coinbase_advanced_py client first (if installed)
try:
    # try the most specific import many code-bases use
    from coinbase_advanced_py.client import CoinbaseClient as CAPCoinbaseClient  # type: ignore
    logger.info("[NIJA] Found coinbase_advanced_py.client.CoinbaseClient")
    try:
        # try a common constructor signature
        client = CAPCoinbaseClient(
            api_key=API_KEY, 
            api_secret=API_SECRET, 
            pem_file_path=API_SECRET_PATH, 
            passphrase=PASSPHRASE,
            sandbox=False
        )
        _live = True
        logger.info("[NIJA] Initialized CoinbaseClient (coinbase_advanced_py). Live enabled.")
    except TypeError as te:
        logger.warning(f"[NIJA] CoinbaseClient constructor signature mismatch: {te}. Trying alternate args.")
        # try alternate signatures
        try:
            client = CAPCoinbaseClient(api_key=API_KEY, pem_file_path=API_SECRET_PATH, sandbox=False)
            _live = True
            logger.info("[NIJA] Initialized CoinbaseClient (alternate args). Live enabled.")
        except Exception as e:
            logger.exception("[NIJA] CoinbaseClient init failed, falling back to other import attempts.")
            client = None
except Exception:
    # Not installed or import failed; we'll try other possible packages below
    logger.info("[NIJA] coinbase_advanced_py.client not available.")

# Try top-level coinbase_advanced_py (some versions expose CoinbaseClient at top)
if client is None:
    try:
        import coinbase_advanced_py as cap  # type: ignore
        if hasattr(cap, "CoinbaseClient"):
            logger.info("[NIJA] Found coinbase_advanced_py.CoinbaseClient")
            try:
                client = cap.CoinbaseClient(api_key=API_KEY, pem_file_path=API_SECRET_PATH)
                _live = True
                logger.info("[NIJA] Initialized CoinbaseClient (top-level). Live enabled.")
            except Exception as e:
                logger.exception("[NIJA] coinbase_advanced_py.CoinbaseClient init failed.")
                client = None
    except Exception:
        logger.info("[NIJA] top-level coinbase_advanced_py import failed or not present.")

# Try coinbase REST client (many libs expose coinbase.rest.RESTClient)
if client is None:
    try:
        from coinbase.rest import RESTClient  # type: ignore
        logger.info("[NIJA] Found coinbase.rest.RESTClient")
        # build kwargs cautiously — different versions accept different names
        kwargs = {}
        if API_KEY:
            kwargs["key"] = API_KEY
        if API_SECRET_PATH:
            kwargs["secret_path"] = API_SECRET_PATH
        elif API_SECRET:
            kwargs["secret"] = API_SECRET
        # some versions accept sandbox boolean
        if os.getenv("SANDBOX", "").lower() in ("1","true","yes"):
            kwargs["sandbox"] = True
        # try constructing, gracefully handling TypeError for unknown args
        try:
            client = RESTClient(**kwargs)
            _live = True
            logger.info("[NIJA] Initialized RESTClient. Live enabled.")
        except TypeError as te:
            # drop passphrase / sandbox if not supported
            kwargs.pop("passphrase", None)
            kwargs.pop("sandbox", None)
            client = RESTClient(**kwargs)
            _live = True
            logger.info("[NIJA] Initialized RESTClient with reduced kwargs. Live enabled.")
    except Exception:
        logger.info("[NIJA] coinbase.rest.RESTClient import failed or not present.")

# Final fallback to Dummy
if client is None:
    _use_dummy("[NIJA] Coinbase client not available or failed to initialize. Using DummyClient.")

# Public helpers
def is_live() -> bool:
    """Return True if running with a real Coinbase client."""
    return _live

def get_accounts() -> Any:
    try:
        return client.get_accounts()
    except Exception as e:
        logger.exception("[NIJA] get_accounts failed; switching to Dummy mode")
        _use_dummy("Switching to Dummy after get_accounts failure.")
        return client.get_accounts()

def place_order(*args, **kwargs) -> Any:
    try:
        return client.place_order(*args, **kwargs)
    except Exception as e:
        logger.exception("[NIJA] place_order failed")
        raise
