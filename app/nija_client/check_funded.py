# app/nija_client/check_funded.py
"""
check_funded_accounts() -> bool

- Returns True if we detect any funded account (basic heuristic: numeric available/balance > 0).
- Fallbacks:
  * If FORCE_FUNDED=1 or FUNDING_OK=1 -> returns True (useful for CI/Render until you wire real keys).
  * Tries to import your vendored Coinbase client module(s) with multiple import paths.
  * Tries several common client constructors/methods (Client, RestClient, client.Client).
  * Logs clear debug messages and never raises on import failures (just returns False).
"""

import os
import traceback
from typing import Any, Iterable

_FORCE = os.getenv("FORCE_FUNDED", "") == "1" or os.getenv("FUNDING_OK", "") == "1"

def _is_numeric_balance(val: Any) -> float:
    """Try to extract a numeric amount from various shapes: dict, object, string."""
    try:
        if val is None:
            return 0.0
        if isinstance(val, (int, float)):
            return float(val)
        if isinstance(val, str):
            # strip common currency symbols
            s = val.replace(",", "").strip()
            for ch in ("$", "USD", "usd"):
                s = s.replace(ch, "")
            return float(s) if s != "" else 0.0
        if isinstance(val, dict):
            # common dict shapes: {"amount": "1.23"} or {"balance": {"amount": "1.23", "currency": "USD"}}
            if "amount" in val:
                return _is_numeric_balance(val["amount"])
            if "balance" in val:
                return _is_numeric_balance(val["balance"])
            if "available" in val:
                return _is_numeric_balance(val["available"])
            # try first numeric-like field
            for v in val.values():
                try:
                    return _is_numeric_balance(v)
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
        pass
    return 0.0

def _iter_accounts_from_client(client: Any) -> Iterable:
    """
    Given a client instance, try to obtain an iterable of account-like objects/dicts.
    We'll probe common patterns and yield account objects.
    """
    # common tidy wrappers / methods
    method_candidates = [
        "list_accounts",  # some libs
        "get_accounts",
        "accounts",       # property or namespace
        "list_accounts_paginated",
        "get_all_accounts",
        "get_account",
    ]
    for name in method_candidates:
        try:
            attr = getattr(client, name, None)
            if callable(attr):
                # call, expect iterable or generator
                items = attr()
                if items is None:
                    continue
                # if generator-like, yield from it
                try:
                    for it in items:
                        yield it
                    return
                except TypeError:
                    # not iterable or returned single value
                    if isinstance(items, (list, tuple)):
                        for it in items:
                            yield it
                        return
                    else:
                        # single item
                        yield items
                        return
            elif attr is not None:
                # attribute that might be an iterable (e.g. client.accounts)
                if isinstance(attr, (list, tuple)):
                    for it in attr:
                        yield it
                    return
                # if attribute provides .list()
                try:
                    getter = getattr(attr, "list", None)
                    if getter and callable(getter):
                        for it in getter():
                            yield it
                        return
                except Exception:
                    pass
        except Exception:
            # ignore and try next
            continue

    # last-ditch: some clients expose a low-level transport 'request' method or 'http_client'
    for alt in ("request", "get", "http_get"):
        if hasattr(client, alt) and callable(getattr(client, alt)):
            try:
                # we won't call arbitrary methods here (unsafe) — so skip
                pass
            except Exception:
                pass

    # nothing found
    return
    yield  # make it a generator

def check_funded_accounts() -> bool:
    # quick test hooks
    if _FORCE:
        print("[INFO] FORCE_FUNDED or FUNDING_OK set -> reporting funded (FORCE).")
        return True

    tried = []
    # candidate import paths for your vendored coinbase library
    import_paths = [
        "cd.vendor.coinbase_advanced_py.client",  # your repo vendor path
        "cd.vendor.coinbase_advanced_py",         # package root
        "coinbase_advanced_py.client",            # alternative
        "coinbase_advanced.client",               # wild guess
        "coinbase.client",                        # wild guess
    ]

    client_module = None
    for path in import_paths:
        try:
            module = __import__(path, fromlist=["*"])
            client_module = module
            print(f"[INFO] Imported vendored client module: {path}")
            break
        except Exception as e:
            tried.append((path, str(e)))
            # continue searching
    if client_module is None:
        print("[WARN] Could not import vendored coinbase client; tried:", tried)
        print("[WARN] If you want to bypass this check during deploy, set FORCE_FUNDED=1 or FUNDING_OK=1 in env.")
        return False

    # find a constructor for client
    constructor = None
    for name in ("Client", "RestClient", "CoinbaseClient", "ClientV2"):
        constructor = getattr(client_module, name, None)
        if callable(constructor):
            print(f"[INFO] Using client constructor: {name}")
            break
        constructor = None

    # sometimes client sits under module.client (if we imported package root)
    if constructor is None and hasattr(client_module, "client"):
        sub = client_module.client
        for name in ("Client", "RestClient", "ClientV2"):
            constructor = getattr(sub, name, None)
            if callable(constructor):
                print(f"[INFO] Using client constructor from submodule.client: {name}")
                break
        if constructor is None:
            constructor = getattr(sub, "__class__", None)

    if constructor is None:
        print("[WARN] No obvious Client constructor found in vendored module; giving up import path.")
        return False

    # read creds from env
    api_key = os.getenv("COINBASE_API_KEY") or os.getenv("API_KEY") or os.getenv("CB_API_KEY")
    api_secret = os.getenv("COINBASE_API_SECRET") or os.getenv("API_SECRET") or os.getenv("CB_API_SECRET")
    api_sub = os.getenv("COINBASE_API_SUB") or os.getenv("API_SUB")

    # If creds are not present, we can't reach coinbase — bail safely (allow FORCE to pass during testing)
    if not api_key or not api_secret:
        print("[WARN] Coinbase API credentials missing (COINBASE_API_KEY/COINBASE_API_SECRET).")
        return False

    # instantiate client (try several ctor signatures)
    client_instance = None
    try_signatures = [
        (api_key, api_secret),
        (api_key, api_secret, api_sub),
        (),
    ]
    for sig in try_signatures:
        try:
            client_instance = constructor(*sig) if sig else constructor()
            print(f"[INFO] Created client instance using signature length={len(sig)}")
            break
        except TypeError as e:
            # wrong signature: keep trying
            continue
        except Exception as e:
            print("[ERROR] client constructor raised exception:", e)
            traceback.print_exc()
            return False

    if client_instance is None:
        print("[ERROR] Failed to instantiate client with any known signature.")
        return False

    # try to iterate accounts and look for positive balance
    try:
        for acct in _iter_accounts_from_client(client_instance):
            try:
                num = _is_numeric_balance(acct)
                if num and num > 0:
                    print(f"[INFO] Found funded account candidate with numeric balance {num} (acct: {acct})")
                    return True
            except Exception:
                # try to inspect as dict or attributes
                try:
                    # common shapes: acct.balance.amount, acct["balance"]["amount"], acct.available
                    if isinstance(acct, dict):
                        # search common keys
                        for key in ("available", "balance", "amount"):
                            if key in acct:
                                val = acct[key]
                                num = _is_numeric_balance(val)
                                if num and num > 0:
                                    print(f"[INFO] Found funded account (dict) {num} {key}")
                                    return True
                    else:
                        for attr in ("available", "balance", "amount"):
                            if hasattr(acct, attr):
                                val = getattr(acct, attr)
                                num = _is_numeric_balance(val)
                                if num and num > 0:
                                    print(f"[INFO] Found funded account (obj) {attr}={num}")
                                    return True
                except Exception:
                    pass
        # if we reach here no positive balances found
        print("[INFO] No account with positive numeric balance detected.")
        return False
    except Exception as e:
        print("[ERROR] Exception while enumerating accounts:", e)
        traceback.print_exc()
        return False
