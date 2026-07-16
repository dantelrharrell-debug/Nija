"""Repair auth-hook recursion and fail closed on uninitialized broker clients."""
from __future__ import annotations

import logging
import os
import sys
import threading
from functools import wraps
from types import ModuleType
from typing import Any, Callable

logger = logging.getLogger("nija.runtime_auth_endpoint_repair")
_MARKER = "20260716-auth-endpoint-v2"
_LOCK = threading.RLock()
_PATCHED = False
_LOCAL = threading.local()


def _set_okx_endpoint(instance: Any, url: str) -> None:
    os.environ["OKX_BASE_URL"] = url
    for attr in ("base_url", "api_base_url", "endpoint", "api_url", "rest_url"):
        if hasattr(instance, attr):
            try:
                setattr(instance, attr, url)
            except Exception:
                pass


def _zero_coinbase_balance() -> dict[str, Any]:
    return {
        "usd": 0.0,
        "usdc": 0.0,
        "trading_balance": 0.0,
        "usd_held": 0.0,
        "usdc_held": 0.0,
        "total_held": 0.0,
        "total_funds": 0.0,
        "crypto": {},
        "consumer_usd": 0.0,
        "consumer_usdc": 0.0,
        "connected": False,
        "reason": "coinbase_client_uninitialized",
    }


def _mark_coinbase_disconnected(instance: Any, reason: str) -> None:
    for attr, value in (("connected", False), ("_is_available", False), ("_auth_failed", True)):
        try:
            setattr(instance, attr, value)
        except Exception:
            pass
    os.environ["NIJA_COINBASE_CONNECTED"] = "0"
    os.environ["NIJA_COINBASE_BALANCE_OBSERVED"] = "0"
    os.environ["NIJA_COINBASE_SPENDABLE_QUOTE"] = "0.00000000"
    os.environ["NIJA_COINBASE_FUNDING_STATUS"] = reason


def _patch_coinbase_class(module: ModuleType) -> bool:
    global _PATCHED
    cls = getattr(module, "CoinbaseBroker", None)
    if not isinstance(cls, type):
        return False

    changed = False
    for method_name in ("_get_account_balance_detailed", "get_account_balance", "get_balance"):
        original = getattr(cls, method_name, None)
        if not callable(original) or getattr(original, "_nija_coinbase_client_guard_v2", False):
            continue

        @wraps(original)
        def guarded(self: Any, *args: Any, __original: Callable[..., Any] = original,
                    __method_name: str = method_name, **kwargs: Any) -> Any:
            client = getattr(self, "client", None)
            if client is None:
                _mark_coinbase_disconnected(self, "client_uninitialized")
                logger.error(
                    "COINBASE_CLIENT_UNINITIALIZED_FAIL_CLOSED marker=%s method=%s action=zero_balance_no_api_call",
                    _MARKER,
                    __method_name,
                )
                return _zero_coinbase_balance()
            return __original(self, *args, **kwargs)

        guarded._nija_coinbase_client_guard_v2 = True  # type: ignore[attr-defined]
        guarded.__wrapped__ = original  # type: ignore[attr-defined]
        setattr(cls, method_name, guarded)
        changed = True

    if changed:
        _PATCHED = True
        logger.warning("COINBASE_CLIENT_FAIL_CLOSED_GUARD_PATCHED marker=%s class=%s", _MARKER, cls.__name__)
    return changed


def _patch_okx_class(module: ModuleType) -> bool:
    global _PATCHED
    cls = getattr(module, "OKXBroker", None)
    if not isinstance(cls, type):
        return False
    original = getattr(cls, "connect", None)
    if not callable(original) or getattr(original, "_nija_endpoint_instance_repair_v2", False):
        return False

    @wraps(original)
    def connect(self: Any, *args: Any, __original: Callable[..., Any] = original, **kwargs: Any) -> Any:
        active = getattr(_LOCAL, "okx_connect_active", set())
        identity = id(self)
        if identity in active:
            try:
                self.connected = False
            except Exception:
                pass
            os.environ["NIJA_OKX_CONNECTED"] = "0"
            os.environ["NIJA_OKX_FUNDING_STATUS"] = "connect_recursion_blocked"
            logger.error(
                "OKX_CONNECT_REENTRY_BLOCKED marker=%s class=%s action=fail_closed",
                _MARKER,
                type(self).__name__,
            )
            return False

        active = set(active)
        active.add(identity)
        _LOCAL.okx_connect_active = active
        try:
            configured = str(os.environ.get("OKX_BASE_URL", "") or "").strip().rstrip("/")
            if configured:
                _set_okx_endpoint(self, configured)
            result = __original(self, *args, **kwargs)
            configured_after = str(os.environ.get("OKX_BASE_URL", "") or "").strip().rstrip("/")
            if configured_after and configured_after != configured:
                _set_okx_endpoint(self, configured_after)
            return result
        except RecursionError as exc:
            try:
                self.connected = False
            except Exception:
                pass
            os.environ["NIJA_OKX_CONNECTED"] = "0"
            os.environ["NIJA_OKX_FUNDING_STATUS"] = "connect_recursion_blocked"
            logger.error(
                "OKX_CONNECT_RECURSION_FAIL_CLOSED marker=%s class=%s error=%s",
                _MARKER,
                type(self).__name__,
                str(exc)[:160],
            )
            return False
        finally:
            current = set(getattr(_LOCAL, "okx_connect_active", set()))
            current.discard(identity)
            _LOCAL.okx_connect_active = current

    connect._nija_endpoint_instance_repair_v2 = True  # type: ignore[attr-defined]
    connect.__wrapped__ = original  # type: ignore[attr-defined]
    setattr(cls, "connect", connect)
    _PATCHED = True
    logger.warning("OKX_INSTANCE_ENDPOINT_REPAIR_PATCHED marker=%s class=%s reentry_guard=true", _MARKER, cls.__name__)
    return True


def _disable_recursive_convergence_hook() -> None:
    module = sys.modules.get("runtime_convergence_hardening_patch")
    if not isinstance(module, ModuleType):
        return

    def safe_patch_auth_surface(target: ModuleType) -> bool:
        auth = sys.modules.get("broker_auth_recovery_patch")
        if not isinstance(auth, ModuleType):
            return False
        patched = False
        for attr_name in dir(target):
            cls = getattr(target, attr_name, None)
            if not isinstance(cls, type):
                continue
            lowered = attr_name.lower()
            venue = "coinbase" if "coinbase" in lowered else "okx" if "okx" in lowered else ""
            if not venue:
                continue
            for method_name in ("connect", "verify_connection", "test_connection"):
                original = getattr(cls, method_name, None)
                if not callable(original) or getattr(original, "_nija_runtime_convergence_auth_safe_v2", False):
                    continue

                @wraps(original)
                def wrapped(self: Any, *args: Any, __original: Callable[..., Any] = original,
                            __venue: str = venue, **kwargs: Any) -> Any:
                    normalizer = getattr(auth, f"normalize_{__venue}_environment", None)
                    if callable(normalizer):
                        normalizer()
                    if __venue == "okx":
                        url = str(os.environ.get("OKX_BASE_URL", "") or "").strip().rstrip("/")
                        if url:
                            _set_okx_endpoint(self, url)
                    return __original(self, *args, **kwargs)

                wrapped._nija_runtime_convergence_auth_safe_v2 = True  # type: ignore[attr-defined]
                wrapped.__wrapped__ = original  # type: ignore[attr-defined]
                setattr(cls, method_name, wrapped)
                patched = True
        return patched

    module._patch_auth_surface = safe_patch_auth_surface
    logger.warning("RUNTIME_CONVERGENCE_RECURSION_REPAIRED marker=%s", _MARKER)


def install() -> None:
    with _LOCK:
        _disable_recursive_convergence_hook()
        for name in ("bot.broker_manager", "broker_manager"):
            module = sys.modules.get(name)
            if isinstance(module, ModuleType):
                _patch_coinbase_class(module)
                _patch_okx_class(module)
        os.environ["NIJA_RUNTIME_AUTH_ENDPOINT_REPAIR_INSTALLED"] = "1"
        logger.warning("RUNTIME_AUTH_ENDPOINT_REPAIR_INSTALLED marker=%s patched=%s", _MARKER, _PATCHED)


def installed() -> bool:
    return _PATCHED


__all__ = [
    "install",
    "installed",
    "_set_okx_endpoint",
    "_zero_coinbase_balance",
    "_patch_coinbase_class",
    "_patch_okx_class",
]
