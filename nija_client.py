# nija_client.py
"""
Final robust Coinbase client initializer for NIJA — ready to paste.
- Attempts several import/constructor patterns safely.
- Handles RESTBase unexpected kwargs (e.g. 'passphrase').
- Dynamic discovery of client-like classes inside coinbase_advanced_py.
- Clear logs and safe DummyClient fallback so service stays up.
"""

import os
import logging
import importlib
import pkgutil
import traceback
from typing import Any, Dict, List

# ---------- Logging ----------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_client")

# ---------- Environment / Paths ----------
COINBASE_PEM_PATH = "/opt/render/project/secrets/coinbase.pem"
COINBASE_PEM_CONTENT = os.environ.get("COINBASE_PEM_CONTENT")
COINBASE_API_KEY = os.environ.get("COINBASE_API_KEY")
COINBASE_API_SECRET = os.environ.get("COINBASE_API_SECRET")
COINBASE_API_SECRET_PATH = os.environ.get("COINBASE_API_SECRET_PATH")
COINBASE_PASSPHRASE = os.environ.get("COINBASE_PASSPHRASE")
SANDBOX = os.environ.get("SANDBOX")
DRY_RUN = os.environ.get("DRY_RUN", "True").lower() == "true"

# ---------- Ensure PEM exists (no-op if start.sh wrote it) ----------
def ensure_pem():
    try:
        if COINBASE_PEM_CONTENT and not os.path.exists(COINBASE_PEM_PATH):
            os.makedirs(os.path.dirname(COINBASE_PEM_PATH), exist_ok=True)
            with open(COINBASE_PEM_PATH, "w", encoding="utf-8") as f:
                f.write(COINBASE_PEM_CONTENT)
            os.chmod(COINBASE_PEM_PATH, 0o600)
            logger.info("[NIJA] Wrote PEM from env to %s", COINBASE_PEM_PATH)
        elif os.path.exists(COINBASE_PEM_PATH):
            logger.info("[NIJA] PEM found at %s", COINBASE_PEM_PATH)
        else:
            logger.info("[NIJA] No PEM present at %s (start.sh should write it)", COINBASE_PEM_PATH)
    except Exception:
        logger.exception("[NIJA] ensure_pem failed")

ensure_pem()

# ---------- Dummy fallback ----------
class DummyClient:
    def __init__(self):
        logger.info("[NIJA-DUMMY] DummyClient active (no live Coinbase client).")

    def get_accounts(self) -> List[Dict[str, Any]]:
        logger.info("[NIJA-DUMMY] get_accounts called")
        return [{"currency": "USD", "balance": "1000"}]

    def place_order(self, *args, **kwargs) -> Dict[str, Any]:
        logger.info("[NIJA-DUMMY] place_order called (dummy). args=%s kwargs=%s", args, kwargs)
        return {"id": "dummy-order", "status": "created", "args": args, "kwargs": kwargs}

    def __repr__(self):
        return "<DummyClient>"

client = None
attempts = []

# ---------- Safe constructor helper ----------
def try_construct(name: str, ctor, kw: Dict[str, Any]):
    try:
        inst = ctor(**kw)
        logger.info("[NIJA] Constructed %s with kwargs: %s", name,
                    {k: ("<redacted>" if "key" in k or "secret" in k or "pem" in k or "pass" in k else v)
                     for k, v in kw.items()})
        return inst
    except TypeError as te:
        # return TypeError so caller can try alternate kwargs
        logger.debug("[NIJA] TypeError constructing %s: %s", name, te)
        raise
    except Exception:
        logger.debug("[NIJA] Exception constructing %s: %s", name, traceback.format_exc())
        raise

# ---------- Attempt 1: coinbase_advanced_py.client.CoinbaseClient ----------
try:
    attempts.append("coinbase_advanced_py.client import")
    mod = importlib.import_module("coinbase_advanced_py.client")
    if hasattr(mod, "CoinbaseClient"):
        CoinbaseClient = getattr(mod, "CoinbaseClient")
        # try common kwarg sets
        candidate_kwargs = []
        if COINBASE_API_KEY and os.path.exists(COINBASE_PEM_PATH):
            candidate_kwargs.append({"api_key": COINBASE_API_KEY, "pem_file_path": COINBASE_PEM_PATH})
        if COINBASE_API_KEY and COINBASE_PASSPHRASE:
            candidate_kwargs.append({"api_key": COINBASE_API_KEY, "passphrase": COINBASE_PASSPHRASE})
        if not candidate_kwargs:
            candidate_kwargs = [{"api_key": COINBASE_API_KEY}] if COINBASE_API_KEY else [{}]
        for kw in candidate_kwargs:
            try:
                client = try_construct("coinbase_advanced_py.client.CoinbaseClient", CoinbaseClient, kw)
                break
            except TypeError:
                continue
            except Exception:
                continue
except ModuleNotFoundError:
    attempts.append("coinbase_advanced_py.client not found")
except Exception:
    logger.debug("[NIJA] attempt1 error: %s", traceback.format_exc())

# ---------- Attempt 2: top-level coinbase_advanced_py.CoinbaseClient ----------
if client is None:
    try:
        attempts.append("coinbase_advanced_py top-level import")
        pkg = importlib.import_module("coinbase_advanced_py")
        if hasattr(pkg, "CoinbaseClient"):
            CoinbaseClient = getattr(pkg, "CoinbaseClient")
            kw = {}
            if COINBASE_API_KEY and os.path.exists(COINBASE_PEM_PATH):
                kw = {"api_key": COINBASE_API_KEY, "pem_file_path": COINBASE_PEM_PATH}
            elif COINBASE_API_KEY:
                kw = {"api_key": COINBASE_API_KEY}
            try:
                client = try_construct("coinbase_advanced_py.CoinbaseClient", CoinbaseClient, kw)
            except TypeError:
                pass
    except ModuleNotFoundError:
        attempts.append("coinbase_advanced_py top-level not installed")
    except Exception:
        logger.debug("[NIJA] attempt2 error: %s", traceback.format_exc())

# ---------- Attempt 3: coinbase.rest.RESTClient (try safe kwargs, avoid passphrase if it breaks) ----------
if client is None:
    try:
        attempts.append("coinbase.rest import")
        mod_rest = importlib.import_module("coinbase.rest")
        if hasattr(mod_rest, "RESTClient"):
            RESTClient = getattr(mod_rest, "RESTClient")
            tried = False
            # try patterns that RESTClient often accepts, but avoid 'passphrase' first
            rest_candidates = []
            if COINBASE_API_KEY and COINBASE_API_SECRET_PATH:
                rest_candidates.append({"key": COINBASE_API_KEY, "secret_path": COINBASE_API_SECRET_PATH})
            if COINBASE_API_KEY and COINBASE_API_SECRET:
                rest_candidates.append({"key": COINBASE_API_KEY, "secret": COINBASE_API_SECRET})
            # last resort: include passphrase only if above fail and passphrase present
            if COINBASE_PASSPHRASE:
                rest_candidates.append({"key": COINBASE_API_KEY, "passphrase": COINBASE_PASSPHRASE})
            for kw in rest_candidates or ([{}] if COINBASE_API_KEY else [{}]):
                try:
                    client = try_construct("coinbase.rest.RESTClient", RESTClient, kw)
                    tried = True
                    break
                except TypeError:
                    # TypeError means kwarg mismatch; try next candidate without that kw
                    continue
                except Exception:
                    continue
            if not tried and client is None:
                attempts.append("RESTClient tried but couldn't construct with available kwargs")
    except ModuleNotFoundError:
        attempts.append("coinbase.rest not found")
    except Exception:
        logger.debug("[NIJA] attempt3 error: %s", traceback.format_exc())

# ---------- Attempt 4: dynamic discovery inside coinbase_advanced_py ----------
def dynamic_discover(pkg_name="coinbase_advanced_py"):
    global client
    try:
        pkg = importlib.import_module(pkg_name)
    except Exception:
        return None

    # Try top-level attributes first
    for attr in dir(pkg):
        if "Client" in attr or attr.lower().endswith("client"):
            try:
                ctor = getattr(pkg, attr)
                if callable(ctor):
                    kwargs_candidates = []
                    if COINBASE_API_KEY and os.path.exists(COINBASE_PEM_PATH):
                        kwargs_candidates.append({"api_key": COINBASE_API_KEY, "pem_file_path": COINBASE_PEM_PATH})
                    if COINBASE_API_KEY and COINBASE_API_SECRET_PATH:
                        kwargs_candidates.append({"key": COINBASE_API_KEY, "secret_path": COINBASE_API_SECRET_PATH})
                    if not kwargs_candidates:
                        kwargs_candidates = [{"api_key": COINBASE_API_KEY} if COINBASE_API_KEY else [{}]]
                    for kw in kwargs_candidates:
                        try:
                            inst = try_construct(f"{pkg_name}.{attr}", ctor, kw)
                            return inst
                        except TypeError:
                            continue
                        except Exception:
                            continue
            except Exception:
                continue

    # Walk subpackages/modules
    if hasattr(pkg, "__path__"):
        for finder, name, ispkg in pkgutil.walk_packages(pkg.__path__, prefix=pkg.__name__ + "."):
            try:
                sub = importlib.import_module(name)
                for attr in dir(sub):
                    if "Client" in attr or attr.lower().endswith("client"):
                        try:
                            ctor = getattr(sub, attr)
                            if callable(ctor):
                                kwargs_candidates = []
                                if COINBASE_API_KEY and os.path.exists(COINBASE_PEM_PATH):
                                    kwargs_candidates.append({"api_key": COINBASE_API_KEY, "pem_file_path": COINBASE_PEM_PATH})
                                if COINBASE_API_KEY and COINBASE_API_SECRET_PATH:
                                    kwargs_candidates.append({"key": COINBASE_API_KEY, "secret_path": COINBASE_API_SECRET_PATH})
                                for kw in kwargs_candidates or ([{}]):
                                    try:
                                        inst = try_construct(f"{name}.{attr}", ctor, kw)
                                        return inst
                                    except TypeError:
                                        continue
                                    except Exception:
                                        continue
                        except Exception:
                            continue
            except Exception:
                continue
    return None

if client is None:
    try:
        attempts.append("dynamic discovery")
        client = dynamic_discover("coinbase_advanced_py")
    except Exception:
        logger.debug("[NIJA] dynamic discovery error: %s", traceback.format_exc())

# ---------- Final fallback ----------
if client is None:
    logger.warning("[NIJA] Could not instantiate live Coinbase client. Falling back to DummyClient.")
    logger.info("[NIJA] Import attempts summary: %s", attempts)
    client = DummyClient()
else:
    logger.info("[NIJA] Using live client: %s", type(client).__name__)
    logger.info("[NIJA] SANDBOX=%s DRY_RUN=%s", bool(SANDBOX), DRY_RUN)

# ---------- Exposed adapter functions ----------
def get_accounts():
    try:
        return client.get_accounts()
    except Exception:
        logger.exception("[NIJA] get_accounts failed")
        return []

def place_order(*args, **kwargs):
    try:
        return client.place_order(*args, **kwargs)
    except Exception:
        logger.exception("[NIJA] place_order failed")
        return {"error": "place_order failed"}

def check_live_status() -> bool:
    try:
        if isinstance(client, DummyClient):
            logger.warning("[NIJA] Trading not live (DummyClient active)")
            return False
        accts = client.get_accounts()
        ok = bool(accts)
        if ok:
            logger.info("[NIJA] ✅ Live trading ready (accounts fetched).")
        else:
            logger.warning("[NIJA] Live client present but returned no accounts.")
        return ok
    except Exception:
        logger.exception("[NIJA] check_live_status exception")
        return False

def startup_live_check():
    logger.info("=== NIJA STARTUP LIVE CHECK ===")
    try:
        if check_live_status():
            logger.info("[NIJA] NIJA is live! Ready to trade.")
        else:
            logger.warning("[NIJA] ❌ NIJA is NOT live — using DummyClient")
    except Exception:
        logger.exception("[NIJA] startup_live_check error")

startup_live_check()

__all__ = ["client", "get_accounts", "place_order", "check_live_status", "startup_live_check"]
