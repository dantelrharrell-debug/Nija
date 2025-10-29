# nija_client.py
"""
NIJA Coinbase client initializer — ready to paste.
- Tries common import paths and constructor patterns.
- Performs a dynamic scan of coinbase_advanced_py submodules for classes with "Client" in the name.
- Falls back to DummyClient (keeps service up) if no live client can be instantiated.
- Writes PEM from COINBASE_PEM_CONTENT (if provided) to /opt/render/project/secrets/coinbase.pem.
"""

import os
import logging
import traceback
import importlib
import pkgutil
from typing import Any, Dict, List

# --- Logging ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nija_client")

# --- Environment & paths ---
COINBASE_PEM_PATH = "/opt/render/project/secrets/coinbase.pem"
COINBASE_PEM_CONTENT = os.environ.get("COINBASE_PEM_CONTENT")
COINBASE_API_KEY = os.environ.get("COINBASE_API_KEY")
COINBASE_API_SECRET = os.environ.get("COINBASE_API_SECRET")
COINBASE_API_SECRET_PATH = os.environ.get("COINBASE_API_SECRET_PATH")
COINBASE_PASSPHRASE = os.environ.get("COINBASE_PASSPHRASE")
SANDBOX = os.environ.get("SANDBOX")
DRY_RUN = os.environ.get("DRY_RUN", "True").lower() == "true"

# --- Ensure PEM file (safe if start.sh already wrote it) ---
def ensure_pem():
    try:
        if COINBASE_PEM_CONTENT and not os.path.exists(COINBASE_PEM_PATH):
            os.makedirs(os.path.dirname(COINBASE_PEM_PATH), exist_ok=True)
            with open(COINBASE_PEM_PATH, "w", encoding="utf-8") as f:
                f.write(COINBASE_PEM_CONTENT)
            os.chmod(COINBASE_PEM_PATH, 0o600)
            logger.info("[NIJA] Wrote PEM from env to %s", COINBASE_PEM_PATH)
        elif os.path.exists(COINBASE_PEM_PATH):
            logger.info("[NIJA] PEM present at %s", COINBASE_PEM_PATH)
        else:
            logger.info("[NIJA] PEM not found at %s (start.sh should write it)", COINBASE_PEM_PATH)
    except Exception:
        logger.exception("[NIJA] ensure_pem failed")

ensure_pem()

# --- Dummy fallback client ---
class DummyClient:
    def __init__(self):
        logger.warning("[NIJA-DUMMY] DummyClient active (no live Coinbase client).")

    def get_accounts(self) -> List[Dict[str, Any]]:
        logger.info("[NIJA-DUMMY] get_accounts called")
        return [{"currency": "USD", "balance": "1000"}]

    def place_order(self, *args, **kwargs) -> Dict[str, Any]:
        logger.info("[NIJA-DUMMY] place_order called (dummy). args=%s kwargs=%s", args, kwargs)
        return {"id": "dummy-order", "status": "created", "args": args, "kwargs": kwargs}

    def __repr__(self):
        return "<DummyClient>"

# --- safe constructor attempt helper ---
def try_construct(name: str, ctor, kwargs: dict):
    try:
        inst = ctor(**kwargs)
        safe_kwargs = {k: ("<redacted>" if any(s in k.lower() for s in ("key", "secret", "pem", "pass")) else v)
                       for k, v in kwargs.items()}
        logger.info("[NIJA] Successfully instantiated %s with %s", name, safe_kwargs)
        return inst
    except TypeError as te:
        logger.debug("[NIJA] TypeError constructing %s: %s", name, te)
        raise
    except Exception as e:
        logger.debug("[NIJA] Exception constructing %s: %s", name, traceback.format_exc())
        raise

# --- Try multiple import/constructor patterns ---
client = None
attempts = []

# Pattern A: coinbase_advanced_py.client.CoinbaseClient
try:
    mod = importlib.import_module("coinbase_advanced_py.client")
    if hasattr(mod, "CoinbaseClient"):
        CoinbaseClient = getattr(mod, "CoinbaseClient")
        attempts.append("coinbase_advanced_py.client.CoinbaseClient")
        candidate_kwargs = []
        if COINBASE_API_KEY and os.path.exists(COINBASE_PEM_PATH):
            candidate_kwargs.append({"api_key": COINBASE_API_KEY, "pem_file_path": COINBASE_PEM_PATH})
        if COINBASE_API_KEY and COINBASE_PASSPHRASE:
            candidate_kwargs.append({"api_key": COINBASE_API_KEY, "passphrase": COINBASE_PASSPHRASE})
        for kw in candidate_kwargs:
            try:
                client = try_construct("coinbase_advanced_py.client.CoinbaseClient", CoinbaseClient, kw)
                break
            except Exception:
                continue
except ModuleNotFoundError:
    attempts.append("coinbase_advanced_py.client not found")
except Exception:
    logger.debug("[NIJA] error checking coinbase_advanced_py.client: %s", traceback.format_exc())

# Pattern B: top-level coinbase_advanced_py.CoinbaseClient
if client is None:
    try:
        pkg = importlib.import_module("coinbase_advanced_py")
        if hasattr(pkg, "CoinbaseClient"):
            CoinbaseClient = getattr(pkg, "CoinbaseClient")
            attempts.append("coinbase_advanced_py.CoinbaseClient")
            try:
                if COINBASE_API_KEY and os.path.exists(COINBASE_PEM_PATH):
                    client = try_construct("coinbase_advanced_py.CoinbaseClient", CoinbaseClient,
                                           {"api_key": COINBASE_API_KEY, "pem_file_path": COINBASE_PEM_PATH})
            except Exception:
                pass
    except ModuleNotFoundError:
        attempts.append("coinbase_advanced_py top-level not installed")
    except Exception:
        logger.debug("[NIJA] error importing coinbase_advanced_py: %s", traceback.format_exc())

# Pattern C: coinbase.rest.RESTClient (alternative)
if client is None:
    try:
        rest_mod = importlib.import_module("coinbase.rest")
        if hasattr(rest_mod, "RESTClient"):
            RESTClient = getattr(rest_mod, "RESTClient")
            attempts.append("coinbase.rest.RESTClient")
            candidate_kwargs = []
            if COINBASE_API_KEY and COINBASE_API_SECRET_PATH:
                candidate_kwargs.append({"key": COINBASE_API_KEY, "secret_path": COINBASE_API_SECRET_PATH})
            if COINBASE_API_KEY and COINBASE_API_SECRET:
                candidate_kwargs.append({"key": COINBASE_API_KEY, "secret": COINBASE_API_SECRET})
            for kw in candidate_kwargs:
                try:
                    client = try_construct("coinbase.rest.RESTClient", RESTClient, kw)
                    break
                except Exception:
                    continue
    except ModuleNotFoundError:
        attempts.append("coinbase.rest not found")
    except Exception:
        logger.debug("[NIJA] error importing coinbase.rest: %s", traceback.format_exc())

# Pattern D: dynamic discovery in coinbase_advanced_py package/submodules
def dynamic_discover(pkg_name="coinbase_advanced_py"):
    try:
        pkg = importlib.import_module(pkg_name)
    except Exception:
        logger.debug("[NIJA] dynamic_discover import failed for %s: %s", pkg_name, traceback.format_exc())
        return None

    logger.info("[NIJA] dynamic discovery on package: %s", pkg_name)

    if hasattr(pkg, "__path__"):
        for finder, name, ispkg in pkgutil.walk_packages(pkg.__path__, prefix=pkg.__name__ + "."):
            try:
                sub = importlib.import_module(name)
                candidates = [a for a in dir(sub) if "Client" in a or a.lower().endswith("client")]
                if candidates:
                    logger.info("[NIJA] dynamic: found candidate attrs in %s: %s", name, candidates)
                for a in candidates:
                    ctor = getattr(sub, a)
                    if callable(ctor):
                        kwargs_list = []
                        if COINBASE_API_KEY and os.path.exists(COINBASE_PEM_PATH):
                            kwargs_list.append({"api_key": COINBASE_API_KEY, "pem_file_path": COINBASE_PEM_PATH})
                        if COINBASE_API_KEY and COINBASE_API_SECRET_PATH:
                            kwargs_list.append({"key": COINBASE_API_KEY, "secret_path": COINBASE_API_SECRET_PATH})
                        for kw in kwargs_list:
                            try:
                                inst = try_construct(f"{name}.{a}", ctor, kw)
                                return inst
                            except Exception:
                                continue
            except Exception:
                logger.debug("[NIJA] dynamic import failure for %s: %s", name, traceback.format_exc())
    else:
        # fallback: top-level attrs
        for a in dir(pkg):
            if "Client" in a or a.lower().endswith("client"):
                try:
                    ctor = getattr(pkg, a)
                    if callable(ctor):
                        if COINBASE_API_KEY and os.path.exists(COINBASE_PEM_PATH):
                            try:
                                return try_construct(f"{pkg_name}.{a}", ctor, {"api_key": COINBASE_API_KEY, "pem_file_path": COINBASE_PEM_PATH})
                            except Exception:
                                continue
                except Exception:
                    logger.debug("[NIJA] dynamic top-level attr error: %s", traceback.format_exc())
    return None

if client is None:
    attempts.append("dynamic discovery")
    client = dynamic_discover("coinbase_advanced_py")

# Final fallback
if client is None:
    logger.warning("[NIJA] Could not initialize a live Coinbase client. Falling back to DummyClient.")
    logger.info("[NIJA] Import attempts summary: %s", attempts)
    client = DummyClient()
else:
    logger.info("[NIJA] Using live client: %s", type(client).__name__)
    logger.info("[NIJA] SANDBOX=%s DRY_RUN=%s", bool(SANDBOX), DRY_RUN)

# --- Adapter functions ---
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
