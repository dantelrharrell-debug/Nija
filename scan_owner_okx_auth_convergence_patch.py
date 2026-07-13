"""One-shot broker-auth convergence compatible with legacy NIJA imports.

Scan ownership is delegated to ``scan_wrapper_convergence_repair_patch``. This
module only canonicalizes Coinbase/OKX connection wrappers and never starts a
background repair thread.
"""
from __future__ import annotations

import importlib
import logging
import os
import sys
import threading
from types import ModuleType
from typing import Any, Callable

logger = logging.getLogger("nija.scan_owner_okx_auth_convergence")
MARKER = "20260713f"
_LOCK = threading.RLock()
_INSTALLED = False
_INSTALLING = False


def _auth_module() -> ModuleType | None:
    module = sys.modules.get("broker_auth_recovery_patch")
    return module if isinstance(module, ModuleType) else None


def _apply_okx_url(instance: Any, url: str) -> None:
    normalized = str(url or "").strip().rstrip("/")
    if not normalized:
        return
    os.environ["OKX_BASE_URL"] = normalized
    for attr in ("base_url", "api_base_url", "endpoint", "api_url", "rest_url"):
        try:
            if hasattr(instance, attr):
                setattr(instance, attr, normalized)
        except Exception:
            pass


def _mark_connect(func: Callable[..., Any], venue: str) -> None:
    for attr in (
        "_nija_auth_recovery_20260711n",
        "_nija_auth_v2",
        "_nija_runtime_convergence_auth_e",
        "_nija_runtime_convergence_auth_safe",
        "_nija_final_auth_safe",
    ):
        setattr(func, attr, True)
    if venue == "okx":
        for attr in (
            "_nija_okx_connect_canonical_20260713b",
            "_nija_final_okx_endpoint_e",
            "_nija_endpoint_instance_repair",
        ):
            setattr(func, attr, True)
    else:
        setattr(func, "_nija_coinbase_failfast_20260713b", True)


def _patch_brokers(module: ModuleType) -> bool:
    changed = False
    auth = _auth_module()
    coinbase_cls = getattr(module, "CoinbaseBroker", None)
    okx_cls = getattr(module, "OKXBroker", None)

    if isinstance(coinbase_cls, type):
        current = getattr(coinbase_cls, "connect", None)
        if callable(current) and not getattr(current, "_nija_coinbase_failfast_20260713b", False):
            original = current

            def coinbase_connect(self: Any, *args: Any, **kwargs: Any) -> Any:
                normalizer = getattr(auth, "normalize_coinbase_environment", None) if auth else None
                if callable(normalizer) and not bool(normalizer()):
                    try:
                        self.connected = False
                    except Exception:
                        pass
                    logger.error("COINBASE_INVALID_PEM_ISOLATED marker=%s", MARKER)
                    return False
                return original(self, *args, **kwargs)

            _mark_connect(coinbase_connect, "coinbase")
            coinbase_connect.__wrapped__ = original  # type: ignore[attr-defined]
            setattr(coinbase_cls, "connect", coinbase_connect)
            changed = True

    if isinstance(okx_cls, type):
        current = getattr(okx_cls, "connect", None)
        if callable(current) and not getattr(current, "_nija_okx_connect_canonical_20260713b", False):
            original = current

            def okx_connect(self: Any, *args: Any, **kwargs: Any) -> Any:
                normalizer = getattr(auth, "normalize_okx_environment", None) if auth else None
                if callable(normalizer) and not bool(normalizer()):
                    logger.error("OKX_CREDENTIALS_INCOMPLETE_ISOLATED marker=%s", MARKER)
                    return False
                primary = str(os.environ.get("OKX_BASE_URL", "https://www.okx.com") or "https://www.okx.com").rstrip("/")
                _apply_okx_url(self, primary)
                result = original(self, *args, **kwargs)
                if result or str(os.environ.get("OKX_DISABLE_ENDPOINT_FALLBACK", "")).lower() in {"1", "true", "yes", "on"}:
                    return result
                alternate_fn = getattr(auth, "_alternate_okx_url", None) if auth else None
                alternate = alternate_fn(primary) if callable(alternate_fn) else ""
                if not alternate:
                    return result
                _apply_okx_url(self, alternate)
                for attr, value in (("connected", False), ("client", None), ("_auth_failed", False), ("_is_available", True)):
                    try:
                        setattr(self, attr, value)
                    except Exception:
                        pass
                second = original(self, *args, **kwargs)
                if second:
                    logger.warning("OKX_AUTH_ENDPOINT_RECOVERED marker=%s base_url=%s", MARKER, alternate)
                    return second
                _apply_okx_url(self, primary)
                return second

            _mark_connect(okx_connect, "okx")
            okx_connect.__wrapped__ = original  # type: ignore[attr-defined]
            setattr(okx_cls, "connect", okx_connect)
            logger.critical("OKX_CONNECT_WRAPPER_CANONICALIZED marker=%s watchdog=false", MARKER)
            changed = True
    return changed


def _patch_core(module: ModuleType) -> bool:
    import scan_wrapper_convergence_repair_patch as canonical
    patched = bool(canonical._patch_core_loop(module))
    cls = getattr(module, "NijaCoreLoop", None)
    method = getattr(cls, "run_scan_phase", None) if isinstance(cls, type) else None
    if callable(method):
        setattr(method, "_nija_scan_owner_result_reuse_20260713b", True)
    return patched


def _load_and_patch() -> bool:
    changed = False
    for name in ("bot.broker_manager", "broker_manager"):
        module = sys.modules.get(name)
        if not isinstance(module, ModuleType):
            try:
                module = importlib.import_module(name)
            except Exception:
                continue
        changed = _patch_brokers(module) or changed
    for name in ("bot.nija_core_loop", "nija_core_loop"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            changed = _patch_core(module) or changed
    return changed


def install() -> bool:
    global _INSTALLED, _INSTALLING
    with _LOCK:
        if _INSTALLED:
            return True
        if _INSTALLING:
            return False
        _INSTALLING = True
        try:
            _load_and_patch()
            _INSTALLED = True
            os.environ["NIJA_SCAN_OWNER_OKX_AUTH_CONVERGENCE_INSTALLED"] = "1"
            os.environ["NIJA_RUNTIME_CONVERGENCE_WATCHDOGS_DISABLED"] = "1"
            logger.critical("SCAN_OWNER_OKX_AUTH_CONVERGENCE_INSTALLED marker=%s watchdog=false", MARKER)
            return True
        finally:
            _INSTALLING = False


def installed() -> bool:
    return _INSTALLED


__all__ = ["install", "installed", "_patch_core", "_patch_brokers", "_apply_okx_url"]
