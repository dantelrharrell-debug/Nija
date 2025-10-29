# nija_client.py
"""
Robust Coinbase client initializer for NIJA (final ready-to-paste).
- Multi-path import attempts + constructor signature trials.
- Dynamic discovery: scans the installed coinbase_advanced_py package and submodules
  looking for any class with 'Client' in the name and tries to instantiate it.
- Clear logging so render logs show what was found/tried.
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

# --- Env and paths ---
COINBASE_PEM_PATH = "/opt/render/project/secrets/coinbase.pem"
COINBASE_PEM_CONTENT_ENV = os.environ.get("COINBASE_PEM_CONTENT")
COINBASE_API_KEY = os.environ.get("COINBASE_API_KEY")
COINBASE_API_SECRET = os.environ.get("COINBASE_API_SECRET")
COINBASE_API_SECRET_PATH = os.environ.get("COINBASE_API_SECRET_PATH")
COINBASE_PASSPHRASE = os.environ.get("COINBASE_PASSPHRASE")
SANDBOX = os.environ.get("SANDBOX")
DRY_RUN = os.environ.get("DRY_RUN", "True").lower() == "true"

# --- Ensure PEM exists (safe no-op if start.sh already wrote it) ---
def ensure_pem():
    try:
        if COINBASE_PEM_CONTENT_ENV and not os.path.exists(COINBASE_PEM_PATH):
            os.makedirs(os.path.dirname(COINBASE_PEM_PATH), exist_ok=True)
            with open(COINBASE_PEM_PATH, "w", encoding="utf-8") as f:
                f.write(COINBASE_PEM_CONTENT_ENV)
            os.chmod(COINBASE_PEM_PATH, 0o600)
            logger.info("[NIJA] Wrote PEM from env to %s", COINBASE_PEM_PATH)
        else:
            if os.path.exists(COINBASE_PEM_PATH):
                logger.info("[NIJA] PEM present at %s", COINBASE_PEM_PATH)
            else:
                logger.info("[NIJA] No PEM found at %s (start.sh should write it)", COINBASE_PEM_PATH)
    except Exception:
        logger.exception("[NIJA] ensure_pem failed")

ensure_pem()

# --- DummyClient fallback ---
class DummyClient:
    def __init__(self):
        logger.info("[NIJA-DUMMY] DummyClient in use (no live Coinbase).")

    def get_accounts(self) -> List[Dict[str, Any]]:
        logger.info("[NIJA-DUMMY] get_accounts called")
        return [{"currency": "USD", "balance": "1000"}]

    def place_order(self, *args, **kwargs) -> Dict[str, Any]:
        logger.info("[NIJA-DUMMY] place_order called (dummy). args=%s kwargs=%s", args, kwargs)
        return {"id": "dummy-order", "status": "created", "args": args, "kwargs": kwargs}

    def __repr__(self):
        return "<DummyClient>"

# --- Helpers for constructor attempts ---
def safe_ctor_try(name: str, ctor, kwargs: dict):
    try:
        inst = ctor(**kwargs)
        logger.info("[NIJA] Successfully created %s using kwargs %s", name, {k: ("<redacted>" if "key" in k or "secret" in k or "pem" in k or "pass" in k else v) for k,v in kwargs.items()})
        return inst
    except TypeError as te:
        # signature mismatch
        logger.debug("[NIJA] TypeError when constructing %s: %s", name, te)
        raise
    except Exception as e:
        logger.debug("[NIJA] Exception when constructing %s: %s", name, traceback.format_exc())
        raise

def redacted(kwargs):
    return {k: ("<redacted>" if "key" in k or "secret" in k or "pem" in k or "pass" in k else v) for k,v in kwargs.items()}

# --- Try a list of common import patterns and kwarg patterns ---
client = None
attempts = []

# 1) Try coinbase_advanced_py.client.CoinbaseClient
try:
    try:
        mod = importlib.import_module("coinbase_advanced_py.client")
        if hasattr(mod, "CoinbaseClient"):
            CoinbaseClient = getattr(mod, "CoinbaseClient")
            attempts.append("import coinbase_advanced_py.client.CoinbaseClient")
            # try common param combos
            candidates = []
            if COINBASE_API_KEY and os.path.exists(COINBASE_PEM_PATH):
                candidates.append({"api_key": COINBASE_API_KEY, "pem_file_path": COINBASE_PEM_PATH})
            if COINBASE_API_KEY and COINBASE_PASSPHRASE:
                candidates.append({"api_key": COINBASE_API_KEY, "passphrase": COINBASE_PASSPHRASE})
            if COINBASE_API_KEY and COINBASE_API_SECRET_PATH:
                candidates.append({"key": COINBASE_API_KEY, "secret_path": COINBASE_API_SECRET_PATH})
            for kw in candidates:
                try:
                    client = safe_ctor_try("coinbase_advanced_py.client.CoinbaseClient", CoinbaseClient, kw)
                    break
                except Exception:
                    continue
    except ModuleNotFoundError:
        attempts.append("coinbase_advanced_py.client not found")
except Exception:
    logger.debug("[NIJA] attempt failed: %s", traceback.format_exc())

# 2) Try top-level coinbase_advanced_py.CoinbaseClient
if client is None:
    try:
        pkg = importlib.import_module("coinbase_advanced_py")
        if hasattr(pkg, "CoinbaseClient"):
            CoinbaseClient = getattr(pkg, "CoinbaseClient")
            attempts.append("import coinbase_advanced_py.CoinbaseClient")
            try:
                if COINBASE_API_KEY and os.path.exists(COINBASE_PEM_PATH):
                    client = safe_ctor_try("coinbase_advanced_py.CoinbaseClient", CoinbaseClient, {"api_key": COINBASE_API_KEY, "pem_file_path": COINBASE_PEM_PATH})
            except Exception:
                pass
    except ModuleNotFoundError:
        attempts.append("coinbase_advanced_py top-level not installed")
    except Exception:
        logger.debug("[NIJA] top-level attempt failed: %s", traceback.format_exc())

# 3) Try coinbase.rest.RESTClient (common alternative)
if client is None:
    try:
        mod_rest = importlib.import_module("coinbase.rest")
        if hasattr(mod_rest, "RESTClient"):
            RESTClient = getattr(mod_rest, "RESTClient")
            attempts.append("import coinbase.rest.RESTClient")
            candidates = []
            if COINBASE_API_KEY and COINBASE_API_SECRET_PATH:
                candidates.append({"key": COINBASE_API_KEY, "secret_path": COINBASE_API_SECRET_PATH})
            if COINBASE_API_KEY and COINBASE_API_SECRET:
                candidates.append({"key": COINBASE_API_KEY, "secret": COINBASE_API_SECRET})
            for kw in candidates:
                try:
                    client = safe_ctor_try("coinbase.rest.RESTClient", RESTClient, kw)
                    break
                except Exception:
                    continue
    except ModuleNotFoundError:
        attempts.append("coinbase.rest not found")
    except Exception:
        logger.debug("[NIJA] coinbase.rest attempt error: %s", traceback.format_exc())

# 4) Dynamic discovery: scan coinbase_advanced_py package and submodules for classes with 'Client' in their name
def dynamic_discover_and_try(pkg_name="coinbase_advanced_py"):
    global client
    try:
        pkg = importlib.import_module(pkg_name)
    except Exception as e:
        logger.debug("[NIJA] dynamic: cannot import %s: %s", pkg_name, e)
        return

    found_attrs = []
    # list top-level attrs
    for attr_name in dir(pkg):
        found_attrs.append(attr_name)

    logger.info("[NIJA] dynamic discovery: top-level attrs in %s -> %s", pkg_name, found_attrs[:40])

    # iterate submodules if it's a package
    if hasattr(pkg, "__path__"):
        for finder, name, ispkg in pkgutil.walk_packages(pkg.__path__, prefix=pkg.__name__ + "."):
            # attempt to import submodule and record its callable attrs
            try:
                sub = importlib.import_module(name)
                sub_attrs = [a for a in dir(sub) if "Client" in a or "client" in a or a.lower().endswith("client")]
                if sub_attrs:
                    logger.info("[NIJA] dynamic: found candidate attrs in %s: %s", name, sub_attrs)
                for a in sub_attrs:
                    try:
                        ctor = getattr(sub, a)
                        # only try callables / classes
                        if callable(ctor):
                            # build candidate kwargs heuristically
                            candidates = []
                            if COINBASE_API_KEY and os.path.exists(COINBASE_PEM_PATH):
                                candidates.append({"api_key": COINBASE_API_KEY, "pem_file_path": COINBASE_PEM_PATH})
                            if COINBASE_API_KEY and COINBASE_API_SECRET_PATH:
                                candidates.append({"key": COINBASE_API_KEY, "secret_path": COINBASE_API_SECRET_PATH})
                            if COINBASE_API_KEY and COINBASE_API_SECRET:
                                candidates.append({"key": COINBASE_API_KEY, "secret": COINBASE_API_SECRET})
                            for kw in candidates:
                                try:
                                    inst = safe_ctor_try(f"{name}.{a}", ctor, kw)
                                    logger.info("[NIJA] dynamic discovery instantiated %s", f"{name}.{a}")
                                    return inst
                                except Exception:
                                    continue
                    except Exception:
                        logger.debug("[NIJA] dynamic attr try failed: %s", traceback.format_exc())
            except Exception:
                logger.debug("[NIJA] dynamic import failure for %s: %s", name, traceback.format_exc())
    else:
        # not a package, try top-level client-like classes
        for a in found_attrs:
            if "Client" in a or a.lower().endswith("client"):
                try:
                    ctor = getattr(pkg, a)
                    if callable(ctor):
                        candidates = []
                        if COINBASE_API_KEY and os.path.exists(COINBASE_PEM_PATH):
                            candidates.append({"api_key": COINBASE_API_KEY, "pem_file_path": COINBASE_PEM_PATH})
                        if COINBASE_API_KEY and COINBASE_API_SECRET_PATH:
                            candidates.append({"key": COINBASE_API_KEY, "secret_path": COINBASE_API_SECRET_PATH})
                        for kw in candidates:
                            try:
                                inst = safe_ctor_try(f"{pkg_name}.{a}", ctor, kw)
                                logger.info("[NIJA] dynamic discovery instantiated %s", f"{pkg_name}.{a}")
                                return inst
                            except Exception:
                                continue
                except Exception:
                    logger.debug("[NIJA] dynamic top-level attr try failed: %s", traceback.format_exc())
    return None

if client is None:
    try:
        attempts.append("dynamic discovery scan")
        client = dynamic_discover_and_try("coinbase_advanced_py")
    except Exception:
        logger.debug("[NIJA] dynamic discovery final error: %s", traceback.format_exc())

# 5) Final fallback to DummyClient
if client is None:
    logger.warning("[NIJA] Could not instantiate a live coinbase client. Falling back to DummyClient.")
    logger.info("[NIJA] Import/attempt summary: %s", attempts)
    client = DummyClient()
else:
    logger.info("[NIJA] Using live client: %s", type(client).__name__)
    logger.info("[NIJA] SANDBOX=%s DRY_RUN=%s", bool(SANDBOX), DRY_RUN)

# --- Adapter functions used by the rest of the repo ---
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
        live = check_live_status()
        if live:
            logger.info("[NIJA] NIJA is live! Ready to trade.")
        else:
            logger.warning("[NIJA] ❌ NIJA is NOT live — using DummyClient")
    except Exception:
        logger.exception("[NIJA] startup_live_check error")

startup_live_check()

__all__ = ["client", "get_accounts", "place_order", "check_live_status", "startup_live_check"]
