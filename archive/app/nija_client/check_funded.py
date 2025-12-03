# app/nija_client/check_funded.py
"""
check_funded_accounts() -> bool

Heuristic check for "funded" Coinbase accounts.
- Honors FORCE_FUNDED=1 or FUNDING_OK=1 to bypass real checks (useful in CI/deploy).
- Tries to import common vendored Coinbase client modules (non-blocking).
- Tries several common client constructors and account-listing shapes.
- NEVER raises on import failures; returns boolean.
"""

from __future__ import annotations
import os
import logging
import traceback
from typing import Any, Iterable, Optional

logger = logging.getLogger("nija.check_funded")
logger.addHandler(logging.NullHandler())

_FORCE = os.getenv("FORCE_FUNDED", "") == "1" or os.getenv("FUNDING_OK", "") == "1"

def _is_numeric_balance(val: Any) -> float:
    """Try to extract a numeric amount from various shapes: dict, object, string, number."""
    try:
        if val is None:
            return 0.0
        if isinstance(val, (int, float)):
            return float(val)
        if isinstance(val, str):
            s = val.replace(",", "").strip()
            for ch in ("$", "USD", "usd"):
                s = s.replace(ch, "")
            return float(s) if s != "" else 0.0
        if isinstance(val, dict):
            for key in ("amount", "available", "balance", "qty"):
                if key in val:
                    return _is_numeric_balance(val[key])
            # fallback: try any value
            for v in val.values():
                try:
                    n = _is_numeric_balance(v)
                    if n:
                        return n
                except Exception:
                    continue
            return 0.0
        # generic object with attributes
        for attr in ("available", "balance", "amount", "qty"):
            if hasattr(val, attr):
                try:
                    return _is_numeric_balance(getattr(val, attr))
                except Exception:
                    pass
    except Exception:
        logger.debug("Exception extracting numeric balance", exc_info=True)
    return 0.0

def _iter_accounts_from_client(client: Any) -> Iterable[Any]:
    """Yield account-like objects from a client instance using common accessors."""
    method_candidates = [
        "list_accounts",
        "get_accounts",
        "accounts",
        "list_accounts_paginated",
        "get_all_accounts",
        "get_account",
        "list",
    ]
    for name in method_candidates:
        try:
            attr = getattr(client, name, None)
            if callable(attr):
                items = attr()
                if items is None:
                    continue
                # if iterable
                try:
                    for it in items:
                        yield it
                    return
                except TypeError:
                    # maybe returned single item
                    if isinstance(items, (list, tuple)):
                        for it in items:
                            yield it
                        return
                    yield items
                    return
            elif attr is not None:
                # attribute that might be iterable
                if isinstance(attr, (list, tuple)):
                    for it in attr:
                        yield it
                    return
                getter = getattr(attr, "list", None)
                if getter and callable(getter):
                    for it in getter():
                        yield it
                    return
        except Exception:
            logger.debug("Probe for '%s' failed on client", name, exc_info=True)
            continue
    # nothing found — return empty generator
    return
    yield  # keep generator signature

def check_funded_accounts(timeout_seconds: Optional[float] = None) -> bool:
    """
    Return True if any account with numeric balance > 0 is detected.
    `timeout_seconds` is reserved for future use if you want to add network timeouts.
    """
    if _FORCE:
        logger.info("FORCE_FUNDED or FUNDING_OK set -> reporting funded (FORCE).")
        return True

    # Candidate import paths for vendored coinbase libs (adjust to your repo)
    import_paths = [
        "app.vendor.coinbase_advanced_py.client",
        "app.vendor.coinbase_advanced_py",
        "coinbase_advanced.client",
        "coinbase_advanced",
        "coinbase.client",
        "coinbase",
    ]

    client_module = None
    tried = []
    for path in import_paths:
        try:
            module = __import__(path, fromlist=["*"])
            client_module = module
            logger.info("Imported vendored client module: %s", path)
            break
        except Exception as e:
            tried.append((path, str(e)))
    if client_module is None:
        logger.warning("Could not import vendored coinbase client; tried: %s", tried)
        logger.warning("Set FORCE_FUNDED=1 or FUNDING_OK=1 to bypass check during deploy.")
        return False

    # find a constructor in module or module.client
    constructor = None
    for name in ("Client", "RestClient", "CoinbaseClient", "ClientV2"):
        constructor = getattr(client_module, name, None)
        if callable(constructor):
            logger.debug("Using client constructor: %s", name)
            break
    if constructor is None and hasattr(client_module, "client"):
        sub = client_module.client
        for name in ("Client", "RestClient", "ClientV2"):
            constructor = getattr(sub, name, None)
            if callable(constructor):
                logger.debug("Using client constructor from submodule.client: %s", name)
                break

    if constructor is None:
        logger.warning("No obvious Client constructor found in vendored module.")
        return False

    # Read creds from env
    api_key = os.getenv("COINBASE_API_KEY") or os.getenv("API_KEY") or os.getenv("CB_API_KEY")
    api_secret = os.getenv("COINBASE_API_SECRET") or os.getenv("API_SECRET") or os.getenv("CB_API_SECRET")
    api_sub = os.getenv("COINBASE_API_SUB") or os.getenv("API_SUB")

    if not api_key or not api_secret:
        logger.warning("Coinbase API credentials missing (COINBASE_API_KEY/COINBASE_API_SECRET).")
        return False

    # try to instantiate client using several signatures
    client_instance = None
    try_signatures = [
        (api_key, api_secret),
        (api_key, api_secret, api_sub),
        (),
    ]
    for sig in try_signatures:
        try:
            client_instance = constructor(*sig) if sig else constructor()
            logger.debug("Created client instance using signature length=%d", len(sig))
            break
        except TypeError:
            continue
        except Exception:
            logger.exception("Client constructor raised an exception")
            return False

    if client_instance is None:
        logger.error("Failed to instantiate client with any known signature.")
        return False

    # iterate accounts and search for numeric positive balances
    try:
        for acct in _iter_accounts_from_client(client_instance):
            try:
                num = _is_numeric_balance(acct)
                if num and num > 0:
                    logger.info("Found funded account candidate with numeric balance %s", num)
                    return True
            except Exception:
                # try alternate inspection
                try:
                    if isinstance(acct, dict):
                        for key in ("available", "balance", "amount"):
                            if key in acct:
                                num = _is_numeric_balance(acct[key])
                                if num and num > 0:
                                    logger.info("Found funded account (dict) %s %s", num, key)
                                    return True
                    else:
                        for attr in ("available", "balance", "amount"):
                            if hasattr(acct, attr):
                                val = getattr(acct, attr)
                                num = _is_numeric_balance(val)
                                if num and num > 0:
                                    logger.info("Found funded account (obj) %s=%s", attr, num)
                                    return True
                except Exception:
                    logger.debug("Failed deeper inspection of account object", exc_info=True)
        logger.info("No account with positive numeric balance detected.")
        return False
    except Exception:
        logger.exception("Exception while enumerating accounts")
        return False
