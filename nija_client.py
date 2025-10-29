# nija_client.py
import os
import logging
import inspect
from typing import Any

# ---------- Config ----------
COINBASE_PEM_PATH = "/opt/render/project/secrets/coinbase.pem"
COINBASE_API_KEY = os.environ.get("COINBASE_API_KEY")
SANDBOX = os.environ.get("SANDBOX", "").lower() in ("1", "true", "yes")

# ---------- Logging ----------
logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO").upper())
logger = logging.getLogger("nija_client")

# ---------- Dummy Client Fallback ----------
class DummyClient:
    def __init__(self):
        self._name = "DummyClient"

    def get_accounts(self):
        logger.warning("[DummyClient] get_accounts called - no live trading!")
        return []

    def place_order(self, *args, **kwargs):
        logger.warning("[DummyClient] place_order called - no live trading!")
        return {"status": "dummy"}

    def __repr__(self):
        return "<DummyClient>"

# ---------- Try import RESTClient (robust) ----------
RESTClient = None
try:
    # Try canonical import first
    from coinbase.rest import RESTClient  # type: ignore
    RESTClient = RESTClient
    logger.info("[NIJA] Imported RESTClient from coinbase.rest")
except Exception as e:
    logger.debug("[NIJA] coinbase.rest import failed: %s", e)
    # try alternative candidates
    import importlib
    candidates = [
        "coinbase_advanced_py.client",
        "coinbase_advanced_py.clients",
        "coinbase_advanced_py.api.client",
        "coinbase_advanced_py._client",
        "coinbase.client",
        "coinbase"
    ]
    for candidate in candidates:
        try:
            mod = importlib.import_module(candidate)
            # search attrs
            for attr in ("RESTClient", "CoinbaseClient", "Client", "REST"):
                if hasattr(mod, attr):
                    RESTClient = getattr(mod, attr)
                    logger.info("[NIJA] Found client class '%s' in module %s", attr, candidate)
                    break
            if RESTClient:
                break
        except Exception:
            continue

if RESTClient is None:
    logger.warning("[NIJA] RESTClient/Coinbase client not found in installed packages. Will use DummyClient.")

# ---------- Instantiate client safely ----------

def _instantiate_restclient_safely(client_cls: Any) -> Any:
    """
    Instantiate REST client by matching allowed constructor parameters.
    Avoid passing unsupported kwargs like 'passphrase'.
    """
    if client_cls is None:
        return None

    sig = None
    try:
        sig = inspect.signature(client_cls.__init__)
        logger.info("[NIJA] RESTClient.__init__ signature: %s", sig)
    except Exception as e:
        logger.warning("[NIJA] Could not inspect RESTClient signature: %s", e)

    # Prepare candidate kwargs (common variants across SDKs)
    candidate_kwargs = {
        "key": COINBASE_API_KEY,
        "api_key": COINBASE_API_KEY,
        "secret_path": COINBASE_PEM_PATH,
        "pem_file_path": COINBASE_PEM_PATH,
        "pem_path": COINBASE_PEM_PATH,
        "secret": COINBASE_API_KEY,
        "sandbox": SANDBOX,
        "base_url": None,
    }

    # Build kwargs subset based on signature if available
    init_kwargs = {}
    if sig:
        for name in sig.parameters.keys():
            if name == "self":
                continue
            if name in candidate_kwargs and candidate_kwargs[name] is not None:
                init_kwargs[name] = candidate_kwargs[name]

    # If signature not available or no matches, try a sensible two-arg fallback
    if not init_kwargs:
        # try (key, secret_path) positional style
        try:
            logger.info("[NIJA] Attempting fallback instantiation with (key, secret_path)")
            return client_cls(COINBASE_API_KEY, COINBASE_PEM_PATH)
        except Exception as e:
            logger.debug("[NIJA] Fallback positional instantiation failed: %s", e)
            # try kw with common names
            for k in ("key", "api_key"):
                for s in ("secret_path", "pem_file_path", "pem_path"):
                    try:
                        kwargs = {k: COINBASE_API_KEY, s: COINBASE_PEM_PATH}
                        logger.info("[NIJA] Trying instantiation with kwargs: %s", kwargs.keys())
                        return client_cls(**kwargs)
                    except Exception as ee:
                        logger.debug("[NIJA] Attempt failed for %s: %s", kwargs, ee)
            return None

    # Try instantiate with the derived kwargs
    try:
        logger.info("[NIJA] Instantiating RESTClient with kwargs: %s", list(init_kwargs.keys()))
        return client_cls(**init_kwargs)
    except TypeError as te:
        logger.error("[NIJA] RESTClient init TypeError: %s", te)
        # Narrow the kwargs and retry simple combinations
        for keep_count in range(len(init_kwargs), 0, -1):
            keys = list(init_kwargs.keys())[:keep_count]
            try:
                small_kwargs = {k: init_kwargs[k] for k in keys}
                logger.info("[NIJA] Retrying with smaller kwargs: %s", list(small_kwargs.keys()))
                return client_cls(**small_kwargs)
            except Exception as e:
                logger.debug("[NIJA] Retry failed: %s", e)
        return None
    except Exception as e:
        logger.exception("[NIJA] Unexpected error instantiating RESTClient: %s", e)
        return None

# Validate PEM presence
pem_ok = os.path.exists(COINBASE_PEM_PATH)
if not pem_ok:
    logger.warning("[NIJA] PEM file missing at %s — live client won't start until you add it", COINBASE_PEM_PATH)
if not COINBASE_API_KEY:
    logger.warning("[NIJA] COINBASE_API_KEY env var missing — live client won't start until you set it")

# Instantiate
_client = None
if RESTClient and COINBASE_API_KEY and pem_ok:
    _client = _instantiate_restclient_safely(RESTClient)
    if _client:
        logger.info("[NIJA] Live REST client instantiated: %s", type(_client).__name__)
    else:
        logger.warning("[NIJA] Could not instantiate REST client — falling back to DummyClient")

if not _client:
    _client = DummyClient()

# Exported client
client = _client

# ---------- Public API ----------
def get_accounts():
    return client.get_accounts()

def place_order(*args, **kwargs):
    return client.place_order(*args, **kwargs)

def check_live_status() -> bool:
    """
    Return True if live client appears to be working and returns accounts.
    """
    try:
        if isinstance(client, DummyClient):
            logger.warning("[NIJA] Trading not live (DummyClient active)")
            return False
        accounts = client.get_accounts()
        if accounts:
            logger.info("[NIJA] ✅ Live trading ready")
            return True
        else:
            logger.warning("[NIJA] Client returned no accounts")
            return False
    except Exception as e:
        logger.warning("[NIJA] Exception checking live status: %s", e)
        return False

# ---------- Startup check (runs when module imported) ----------
def startup_live_check():
    logger.info("[NIJA] Performing startup live check...")
    logger.info("[NIJA] Looking for PEM at: %s", COINBASE_PEM_PATH)
    logger.info("[NIJA] COINBASE_API_KEY present: %s", bool(COINBASE_API_KEY))
    # If RESTClient class exists, print its __init__ signature for debugging logs
    try:
        if RESTClient:
            logger.info("[NIJA] REST client class: %s", getattr(RESTClient, "__name__", str(RESTClient)))
            try:
                logger.info("[NIJA] RESTClient.__init__ signature: %s", inspect.signature(RESTClient.__init__))
            except Exception:
                logger.debug("[NIJA] Could not extract RESTClient signature")
    except Exception:
        pass

    live = check_live_status()
    if live:
        logger.info("[NIJA] ✅ Nija trading is LIVE!")
    else:
        logger.warning("[NIJA] ❌ Nija trading is NOT live — using DummyClient")

# Run the startup check immediately
startup_live_check()
