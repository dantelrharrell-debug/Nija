"""Recover a stale Coinbase balance client without weakening authentication.

A connected Coinbase broker can retain a REST client built before CDP credential
normalisation. Position reads may then work through a newer surface while the legacy
balance path latches a 401 as permanent. This patch performs exactly one broker-local
credential rebind and retry on a 401. Invalid credentials still fail closed.
"""
from __future__ import annotations

import importlib
import logging
import os
import sys
import threading
from functools import wraps
from types import ModuleType
from typing import Any, Callable

logger = logging.getLogger("nija.coinbase_balance_auth_convergence")
_MARKER = "20260718-coinbase-balance-auth-v1"
_PATCH_ATTR = "_nija_coinbase_balance_auth_convergence_v1"
_LOCK = threading.RLock()
_INSTALLED = False


def _is_401(exc: BaseException) -> bool:
    text = str(exc or "").lower()
    return any(token in text for token in ("401", "unauthorized", "invalid api key", "invalid_api_key"))


def _normalise() -> bool:
    try:
        module = importlib.import_module("bot.coinbase_funding_readiness_repair_patch")
        fn = getattr(module, "recover_coinbase_environment", None)
        return bool(fn()) if callable(fn) else False
    except Exception as exc:
        logger.error("COINBASE_BALANCE_AUTH_NORMALIZE_FAILED marker=%s error=%s", _MARKER, exc)
        return False


def _rebuild_client(instance: Any) -> bool:
    if not _normalise():
        return False
    key = str(os.environ.get("COINBASE_API_KEY", "") or "").strip()
    secret = str(os.environ.get("COINBASE_API_SECRET", "") or os.environ.get("COINBASE_PEM_CONTENT", "") or "")
    secret = secret.replace("\\n", "\n").strip()
    if not key or "PRIVATE KEY" not in secret:
        return False
    try:
        from coinbase.rest import RESTClient
        client = RESTClient(api_key=key, api_secret=secret)
        # Authenticate before replacing the live client.
        accounts = client.get_accounts()
        instance.client = client
        instance.connected = True
        for attr in ("_accounts_cache", "accounts_cache"):
            try:
                setattr(instance, attr, accounts)
            except Exception:
                pass
        for attr in (
            "_auth_permanently_failed", "auth_permanently_failed", "_permanent_auth_failure",
            "_coinbase_auth_failed", "_auth_failed", "_balance_auth_failed",
        ):
            if hasattr(instance, attr):
                try:
                    setattr(instance, attr, False)
                except Exception:
                    pass
        for attr in ("_balance_cache", "_balance_cache_time"):
            if hasattr(instance, attr):
                try:
                    setattr(instance, attr, None)
                except Exception:
                    pass
        logger.critical("COINBASE_BALANCE_AUTH_CLIENT_REBOUND marker=%s class=%s authenticated=true", _MARKER, type(instance).__name__)
        return True
    except Exception as exc:
        logger.error("COINBASE_BALANCE_AUTH_REBIND_FAILED marker=%s class=%s error_type=%s error=%s", _MARKER, type(instance).__name__, type(exc).__name__, str(exc)[:240])
        return False


def _patch_class(cls: type) -> bool:
    changed = False
    retry = getattr(cls, "_api_call_with_retry", None)
    if callable(retry) and not getattr(retry, _PATCH_ATTR, False):
        @wraps(retry)
        def guarded_retry(self: Any, api_func: Callable[..., Any], *args: Any, **kwargs: Any):
            try:
                return retry(self, api_func, *args, **kwargs)
            except Exception as exc:
                if not _is_401(exc) or bool(getattr(self, "_nija_coinbase_balance_auth_retrying", False)):
                    raise
                self._nija_coinbase_balance_auth_retrying = True
                try:
                    if not _rebuild_client(self):
                        raise
                    # Rebind bound client methods to the newly authenticated client.
                    name = str(getattr(api_func, "__name__", "") or "")
                    replacement = getattr(getattr(self, "client", None), name, None)
                    target = replacement if callable(replacement) else api_func
                    logger.warning("COINBASE_BALANCE_AUTH_RETRY marker=%s method=%s", _MARKER, name or "unknown")
                    return retry(self, target, *args, **kwargs)
                finally:
                    self._nija_coinbase_balance_auth_retrying = False
        setattr(guarded_retry, _PATCH_ATTR, True)
        guarded_retry.__wrapped__ = retry
        cls._api_call_with_retry = guarded_retry
        changed = True

    for method_name in ("_get_account_balance_detailed", "get_account_balance"):
        current = getattr(cls, method_name, None)
        if not callable(current) or getattr(current, _PATCH_ATTR, False):
            continue
        @wraps(current)
        def balance(self: Any, *args: Any, __fn: Callable[..., Any] = current, __name: str = method_name, **kwargs: Any):
            # A live connected client must not remain suppressed by a stale permanent-401 latch.
            if getattr(self, "connected", False) and _normalise():
                for attr in ("_auth_permanently_failed", "auth_permanently_failed", "_permanent_auth_failure", "_balance_auth_failed"):
                    if hasattr(self, attr):
                        try:
                            setattr(self, attr, False)
                        except Exception:
                            pass
            return __fn(self, *args, **kwargs)
        setattr(balance, _PATCH_ATTR, True)
        balance.__wrapped__ = current
        setattr(cls, method_name, balance)
        changed = True
    if changed:
        logger.warning("COINBASE_BALANCE_AUTH_CLASS_PATCHED marker=%s class=%s", _MARKER, cls.__name__)
    return changed


def _patch_loaded() -> bool:
    changed = False
    for name in ("bot.broker_manager", "broker_manager"):
        module = sys.modules.get(name)
        if not isinstance(module, ModuleType):
            continue
        for class_name in ("CoinbaseBroker", "CoinbaseAdvancedTradeBroker"):
            cls = getattr(module, class_name, None)
            if isinstance(cls, type):
                changed = _patch_class(cls) or changed
    return changed


def install() -> bool:
    global _INSTALLED
    with _LOCK:
        for name in ("bot.broker_manager", "broker_manager"):
            try:
                module = importlib.import_module(name)
            except Exception:
                continue
            for class_name in ("CoinbaseBroker", "CoinbaseAdvancedTradeBroker"):
                cls = getattr(module, class_name, None)
                if isinstance(cls, type):
                    _patch_class(cls)
        _patch_loaded()
        _INSTALLED = True
        os.environ["NIJA_COINBASE_BALANCE_AUTH_CONVERGENCE_INSTALLED"] = "1"
        logger.critical("COINBASE_BALANCE_AUTH_CONVERGENCE_INSTALLED marker=%s", _MARKER)
        return True


__all__ = ["install", "_patch_class", "_rebuild_client"]
