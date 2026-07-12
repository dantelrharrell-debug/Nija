"""Repair auth-hook recursion and apply OKX fallback to live broker instances."""
from __future__ import annotations

import logging
import os
import sys
import threading
from types import ModuleType
from typing import Any, Callable

logger = logging.getLogger("nija.runtime_auth_endpoint_repair")
_MARKER = "20260712c"
_LOCK = threading.RLock()
_PATCHED = False


def _set_okx_endpoint(instance: Any, url: str) -> None:
    os.environ["OKX_BASE_URL"] = url
    for attr in ("base_url", "api_base_url", "endpoint", "api_url", "rest_url"):
        if hasattr(instance, attr):
            try:
                setattr(instance, attr, url)
            except Exception:
                pass


def _patch_okx_class(module: ModuleType) -> bool:
    global _PATCHED
    cls = getattr(module, "OKXBroker", None)
    if not isinstance(cls, type):
        return False
    original = getattr(cls, "connect", None)
    if not callable(original) or getattr(original, "_nija_endpoint_instance_repair", False):
        return False

    def connect(self: Any, *args: Any, __original: Callable[..., Any] = original, **kwargs: Any) -> Any:
        configured = str(os.environ.get("OKX_BASE_URL", "") or "").strip().rstrip("/")
        if configured:
            _set_okx_endpoint(self, configured)
        result = __original(self, *args, **kwargs)
        configured_after = str(os.environ.get("OKX_BASE_URL", "") or "").strip().rstrip("/")
        if configured_after and configured_after != configured:
            _set_okx_endpoint(self, configured_after)
        return result

    connect._nija_endpoint_instance_repair = True  # type: ignore[attr-defined]
    connect.__wrapped__ = original  # type: ignore[attr-defined]
    setattr(cls, "connect", connect)
    _PATCHED = True
    logger.warning("OKX_INSTANCE_ENDPOINT_REPAIR_PATCHED marker=%s class=%s", _MARKER, cls.__name__)
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
                if not callable(original) or getattr(original, "_nija_runtime_convergence_auth_safe", False):
                    continue

                def wrapped(self: Any, *args: Any, __original=original, __venue=venue, **kwargs: Any):
                    normalizer = getattr(auth, f"normalize_{__venue}_environment", None)
                    if callable(normalizer):
                        normalizer()
                    if __venue == "okx":
                        url = str(os.environ.get("OKX_BASE_URL", "") or "").strip().rstrip("/")
                        if url:
                            _set_okx_endpoint(self, url)
                    return __original(self, *args, **kwargs)

                wrapped._nija_runtime_convergence_auth_safe = True  # type: ignore[attr-defined]
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
                _patch_okx_class(module)
        logger.warning("RUNTIME_AUTH_ENDPOINT_REPAIR_INSTALLED marker=%s patched=%s", _MARKER, _PATCHED)


def installed() -> bool:
    return _PATCHED


__all__ = ["install", "installed", "_set_okx_endpoint"]
