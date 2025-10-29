# nija_client.py
"""
Robust Coinbase client initializer for NIJA.
- Tries a few common import paths and constructor signatures (non-destructive).
- Falls back to DummyClient if no live client can be created.
- Exposes client, get_accounts, place_order, check_live_status, startup_live_check.
- Logs clearly so you can see what's failing in Render logs.
"""

import os
import logging
import traceback
from typing import Any, Dict, List

# --- Logging setup ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_client")

# --- Environment / paths ---
COINBASE_PEM_PATH = "/opt/render/project/secrets/coinbase.pem"
COINBASE_PEM_CONTENT_ENV = os.environ.get("COINBASE_PEM_CONTENT")  # used by start.sh to write file
COINBASE_API_KEY = os.environ.get("COINBASE_API_KEY")
COINBASE_API_SECRET = os.environ.get("COINBASE_API_SECRET")  # optional
COINBASE_API_SECRET_PATH = os.environ.get("COINBASE_API_SECRET_PATH")  # optional path alternative
COINBASE_PASSPHRASE = os.environ.get("COINBASE_PASSPHRASE")  # optional
SANDBOX = os.environ.get("SANDBOX")  # if set -> sandbox mode
DRY_RUN = os.environ.get("DRY_RUN", "True").lower() == "true"

# --- Helper: write PEM if provided in env (start.sh should already do this but safe to ensure) ---
def ensure_pem():
    try:
        if COINBASE_PEM_CONTENT_ENV and not os.path.exists(COINBASE_PEM_PATH):
            os.makedirs(os.path.dirname(COINBASE_PEM_PATH), exist_ok=True)
            with open(COINBASE_PEM_PATH, "w", encoding="utf-8") as f:
                f.write(COINBASE_PEM_CONTENT_ENV)
            os.chmod(COINBASE_PEM_PATH, 0o600)
            logger.info("[NIJA] Wrote PEM from COINBASE_PEM_CONTENT to %s", COINBASE_PEM_PATH)
        else:
            if os.path.exists(COINBASE_PEM_PATH):
                logger.info("[NIJA] PEM exists at %s", COINBASE_PEM_PATH)
            else:
                logger.info("[NIJA] No PEM content in env and file missing at %s", COINBASE_PEM_PATH)
    except Exception:
        logger.warning("[NIJA] Failed to ensure PEM: %s", traceback.format_exc())

ensure_pem()

# --- DummyClient fallback ---
class DummyClient:
    def __init__(self):
        logger.info("[NIJA-DUMMY] Initialized DummyClient (no live Coinbase access).")

    def get_accounts(self) -> List[Dict[str, Any]]:
        logger.info("[NIJA-DUMMY] get_accounts called")
        # Example shape similar to Coinbase account listing
        return [{"currency": "USD", "balance": "1000"}]

    def place_order(self, *args, **kwargs) -> Dict[str, Any]:
        logger.info("[NIJA-DUMMY] place_order called (dry run or dummy). Args: %s %s", args, kwargs)
        return {"id": "dummy-order", "status": "created", "args": args, "kwargs": kwargs}

    def __repr__(self):
        return "<DummyClient>"

# --- Try multiple imports / initializers ---
client = None
_init_attempts = []

def try_constructor(obj_name: str, ctor, kwargs: dict):
    """Try calling ctor(**kwargs). Return instance or raise."""
    try:
        inst = ctor(**kwargs)
        logger.info("[NIJA] Successfully initialized %s with kwargs %s", obj_name, {k: ("<redacted>" if "key" in k or "secret" in k or "pem" in k or "pass" in k else v) for k,v in kwargs.items()})
        return inst
    except TypeError as te:
        # constructor signature mismatch
        logger.debug("[NIJA] TypeError initializing %s: %s", obj_name, te)
        raise
    except Exception as e:
        logger.warning("[NIJA] Exception initializing %s: %s", obj_name, e)
        raise

# Attempt 1: coinbase_advanced_py.client.CoinbaseClient (common)
try:
    from coinbase_advanced_py.client import CoinbaseClient  # type: ignore
    _init_attempts.append("coinbase_advanced_py.client.CoinbaseClient import ok")
    try:
        # Try common kwarg patterns (non-destructive, only passing env values)
        tried = False
        # Pattern A: api_key + pem_file_path
        if COINBASE_API_KEY and os.path.exists(COINBASE_PEM_PATH):
            try:
                client = try_constructor("coinbase_advanced_py.client.CoinbaseClient", CoinbaseClient, {
                    "api_key": COINBASE_API_KEY,
                    "pem_file_path": COINBASE_PEM_PATH,
                })
                tried = True
            except Exception:
                pass
        # Pattern B: api_key + passphrase
        if not tried and COINBASE_API_KEY and COINBASE_PASSPHRASE:
            try:
                client = try_constructor("coinbase_advanced_py.client.CoinbaseClient", CoinbaseClient, {
                    "api_key": COINBASE_API_KEY,
                    "passphrase": COINBASE_PASSPHRASE,
                })
                tried = True
            except Exception:
                pass
        # Pattern C: key + secret path
        if not tried and COINBASE_API_KEY and COINBASE_API_SECRET_PATH:
            try:
                client = try_constructor("coinbase_advanced_py.client.CoinbaseClient", CoinbaseClient, {
                    "key": COINBASE_API_KEY,
                    "secret_path": COINBASE_API_SECRET_PATH,
                })
                tried = True
            except Exception:
                pass
    except Exception:
        logger.debug("[NIJA] coinbase_advanced_py.CoinbaseClient attempts failed:\n%s", traceback.format_exc())
except Exception as e:
    logger.debug("[NIJA] coinbase_advanced_py.client import failed: %s", e)
    _init_attempts.append("coinbase_advanced_py.client import failed")

# Attempt 2: coinbase_advanced_py top-level CoinbaseClient
if client is None:
    try:
        from coinbase_advanced_py import CoinbaseClient  # type: ignore
        _init_attempts.append("coinbase_advanced_py.CoinbaseClient import ok")
        try:
            if COINBASE_API_KEY and os.path.exists(COINBASE_PEM_PATH):
                client = try_constructor("coinbase_advanced_py.CoinbaseClient", CoinbaseClient, {
                    "api_key": COINBASE_API_KEY,
                    "pem_file_path": COINBASE_PEM_PATH,
                })
        except Exception:
            logger.debug("[NIJA] top-level CoinbaseClient attempts failed:\n%s", traceback.format_exc())
    except Exception as e:
        logger.debug("[NIJA] top-level coinbase_advanced_py import failed: %s", e)
        _init_attempts.append("coinbase_advanced_py top-level import failed")

# Attempt 3: coinbase.rest.RESTClient (older/newer variants)
if client is None:
    try:
        # some SDKs expose coinbase.rest.RESTClient
        from coinbase.rest import RESTClient  # type: ignore
        _init_attempts.append("coinbase.rest.RESTClient import ok")
        try:
            # Try patterns - DO NOT pass both secret and secret_path simultaneously.
            # Pattern: key + secret_path
            if COINBASE_API_KEY and (COINBASE_API_SECRET_PATH or COINBASE_API_SECRET):
                secret_path = COINBASE_API_SECRET_PATH or COINBASE_API_SECRET
                # If COINBASE_API_SECRET is raw secret (not path) we still try to pass as 'secret' only if must.
                kwargs = {}
                # Many RESTClient constructors expect key + secret or key + secret_path (varies by version)
                kwargs_candidates = []
                if COINBASE_API_KEY and secret_path:
                    kwargs_candidates.append({"key": COINBASE_API_KEY, "secret_path": secret_path})
                    kwargs_candidates.append({"api_key": COINBASE_API_KEY, "api_secret_path": secret_path})
                if COINBASE_API_KEY and COINBASE_API_SECRET:
                    kwargs_candidates.append({"key": COINBASE_API_KEY, "secret": COINBASE_API_SECRET})
                    kwargs_candidates.append({"api_key": COINBASE_API_KEY, "api_secret": COINBASE_API_SECRET})
                # try candidates
                for kc in kwargs_candidates:
                    try:
                        client = try_constructor("coinbase.rest.RESTClient", RESTClient, kc)
                        break
                    except Exception:
                        continue
        except Exception:
            logger.debug("[NIJA] coinbase.rest.RESTClient attempts failed:\n%s", traceback.format_exc())
    except Exception as e:
        logger.debug("[NIJA] coinbase.rest import failed: %s", e)
        _init_attempts.append("coinbase.rest import failed")

# Attempt 4: coinbase_advanced_py package might not expose class directly; try searching installed module attrs
if client is None:
    try:
        import importlib
        mod = importlib.import_module("coinbase_advanced_py")
        logger.debug("[NIJA] coinbase_advanced_py module loaded: %s", getattr(mod, "__file__", "<unknown>"))
        # try common attribute names
        for attr in ("Client", "Coinbase", "CoinbaseClient", "RestClient"):
            ctor = getattr(mod, attr, None)
            if ctor:
                try:
                    if COINBASE_API_KEY and os.path.exists(COINBASE_PEM_PATH):
                        client = try_constructor(f"coinbase_advanced_py.{attr}", ctor, {
                            "api_key": COINBASE_API_KEY,
                            "pem_file_path": COINBASE_PEM_PATH
                        })
                        break
                except Exception:
                    continue
    except Exception:
        logger.debug("[NIJA] dynamic inspection of coinbase_advanced_py failed: %s", traceback.format_exc())

# Final fallback to DummyClient
if client is None:
    logger.warning("[NIJA] Coinbase live client could not be instantiated. Falling back to DummyClient.")
    logger.info("[NIJA] Import attempts summary: %s", _init_attempts)
    client = DummyClient()
else:
    logger.info("[NIJA] Using live client: %s", type(client).__name__)
    logger.info("[NIJA] SANDBOX=%s DRY_RUN=%s", bool(SANDBOX), DRY_RUN)

# --- Small adapter functions so rest of repo can call these consistently ---
def get_accounts():
    try:
        return client.get_accounts()
    except Exception as e:
        logger.exception("[NIJA] get_accounts failed: %s", e)
        # On failure, if live client errors, don't crash the whole app; return safe shape
        return []

def place_order(*args, **kwargs):
    try:
        return client.place_order(*args, **kwargs)
    except Exception as e:
        logger.exception("[NIJA] place_order failed: %s", e)
        return {"error": str(e)}

def check_live_status() -> bool:
    """
    Return True if we appear to have a functioning non-dummy client.
    """
    try:
        if isinstance(client, DummyClient):
            logger.warning("[NIJA] Trading not live (DummyClient active)")
            return False
        # small probe: call get_accounts and ensure result is non-empty
        accts = client.get_accounts()
        ok = bool(accts)
        if ok:
            logger.info("[NIJA] ✅ Live trading ready (accounts fetched).")
        else:
            logger.warning("[NIJA] Live client present but returned no accounts.")
        return ok
    except Exception as e:
        logger.warning("[NIJA] Live status check threw: %s", e)
        return False

def startup_live_check():
    logger.info("=== NIJA STARTUP LIVE CHECK ===")
    try:
        live = check_live_status()
        if live:
            logger.info("[NIJA] NIJA is live! Ready to trade.")
        else:
            logger.warning("[NIJA] ❌ NIJA is NOT live — using DummyClient")
    except Exception:
        logger.exception("[NIJA] startup_live_check failed")

# Run startup check on import
startup_live_check()

# Export client for direct use by other code
__all__ = ["client", "get_accounts", "place_order", "check_live_status", "startup_live_check"]
