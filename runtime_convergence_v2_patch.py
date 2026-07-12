"""Targeted follow-up hardening for NIJA runtime convergence.

This module fixes gaps left by the first convergence guard without bypassing
broker authentication, writer authority, risk controls, or exchange validation.
"""
from __future__ import annotations

import importlib
import logging
import os
import sys
import threading
import time
from pathlib import Path
from types import ModuleType
from typing import Any, Callable

logger = logging.getLogger("nija.runtime_convergence_v2")
MARKER = "20260712b"
_LOCK = threading.RLock()
_SCAN_LOCKS: dict[str, threading.Lock] = {}
_SCAN_GUARD = threading.RLock()
_STARTED = False


def _clean(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "_")


def _broker_name(obj: Any) -> str:
    if obj is None:
        return "unknown"
    text = " ".join(
        str(getattr(obj, attr, "") or "")
        for attr in ("broker_type", "broker_name", "name", "exchange", "exchange_name")
    ).lower() + " " + type(obj).__name__.lower()
    for name in ("kraken", "coinbase", "okx", "alpaca", "binance"):
        if name in text:
            return name
    return "unknown"


def _account_id(obj: Any) -> str:
    if obj is None:
        return "platform"
    for attr in ("account_id", "user_id", "account_name", "owner_id"):
        value = getattr(obj, attr, None)
        if value:
            return _clean(value)
    account_type = getattr(obj, "account_type", None)
    value = getattr(account_type, "value", account_type)
    return _clean(value) if value else "platform"


def _identity(obj: Any) -> str:
    identity = f"{_account_id(obj)}:{_broker_name(obj)}"
    if identity == "platform:unknown":
        identity = f"platform:unknown:{id(obj)}"
    return identity


def _normalize_auth(venue: str) -> None:
    auth = importlib.import_module("broker_auth_recovery_patch")
    if venue == "coinbase":
        auth.normalize_coinbase_environment()
    elif venue == "okx":
        auth.normalize_okx_environment()


def _rebind_tracker(instance: Any) -> bool:
    tracker = getattr(instance, "position_tracker", None)
    if tracker is None:
        return False
    current = str(getattr(tracker, "storage_file", "") or "")
    if current and Path(current).name != "positions.json":
        return False
    identity = _identity(instance).replace(":", "_")
    scoped = str(Path(os.getenv("NIJA_POSITION_STATE_DIR", "data")) / f"positions_{identity}.json")
    try:
        setattr(instance, "position_tracker", type(tracker)(scoped))
        logger.warning(
            "POSITION_TRACKER_REBOUND marker=%s identity=%s old=%s new=%s",
            MARKER, identity, current or "unset", scoped,
        )
        return True
    except Exception as exc:
        logger.error(
            "POSITION_TRACKER_REBOUND_FAILED marker=%s identity=%s err=%s",
            MARKER, identity, exc,
        )
        return False


def _patch_broker_classes(module: ModuleType) -> bool:
    patched = False
    for class_name in dir(module):
        cls = getattr(module, class_name, None)
        if not isinstance(cls, type) or "broker" not in class_name.lower():
            continue
        lower = class_name.lower()
        venue = "coinbase" if "coinbase" in lower else "okx" if "okx" in lower else ""
        original = getattr(cls, "__init__", None)
        if callable(original) and not getattr(original, "_nija_convergence_v2", False):
            def init(self: Any, *args: Any, __original: Callable[..., Any] = original,
                     __venue: str = venue, **kwargs: Any) -> None:
                if __venue:
                    _normalize_auth(__venue)
                __original(self, *args, **kwargs)
                _rebind_tracker(self)
            init._nija_convergence_v2 = True  # type: ignore[attr-defined]
            init.__wrapped__ = original  # type: ignore[attr-defined]
            setattr(cls, "__init__", init)
            patched = True
            logger.warning(
                "BROKER_CONSTRUCTOR_CONVERGENCE_PATCHED marker=%s module=%s class=%s venue=%s",
                MARKER, module.__name__, class_name, venue or "other",
            )
        for method_name in ("connect", "verify_connection", "test_connection"):
            method = getattr(cls, method_name, None)
            if not venue or not callable(method) or getattr(method, "_nija_auth_v2", False):
                continue
            def wrapped(self: Any, *args: Any, __method: Callable[..., Any] = method,
                        __venue: str = venue, **kwargs: Any) -> Any:
                _normalize_auth(__venue)
                result = __method(self, *args, **kwargs)
                _rebind_tracker(self)
                return result
            wrapped._nija_auth_v2 = True  # type: ignore[attr-defined]
            wrapped.__wrapped__ = method  # type: ignore[attr-defined]
            setattr(cls, method_name, wrapped)
            patched = True
    return patched


def _patch_core_loop(module: ModuleType) -> bool:
    cls = getattr(module, "NijaCoreLoop", None)
    if not isinstance(cls, type):
        return False
    original = getattr(cls, "run_scan_phase", None)
    if not callable(original) or getattr(original, "_nija_scan_identity_lock_v2", False):
        return False

    def run_scan_phase(self: Any, *args: Any, **kwargs: Any) -> Any:
        broker = kwargs.get("broker") or (args[0] if args else None)
        key = _identity(broker)
        with _SCAN_GUARD:
            lock = _SCAN_LOCKS.setdefault(key, threading.Lock())
        timeout = max(0.01, float(os.getenv("NIJA_ACCOUNT_SCAN_LOCK_TIMEOUT_S", "0.25") or 0.25))
        if not lock.acquire(timeout=timeout):
            logger.critical(
                "DUPLICATE_SCAN_BLOCKED marker=%s identity=%s timeout_s=%.2f",
                MARKER, key, timeout,
            )
            return (0, 1, 0, {"duplicate_scan": 1})
        try:
            return original(self, *args, **kwargs)
        finally:
            lock.release()

    run_scan_phase._nija_scan_identity_lock_v2 = True  # type: ignore[attr-defined]
    run_scan_phase.__wrapped__ = original  # type: ignore[attr-defined]
    setattr(cls, "run_scan_phase", run_scan_phase)
    logger.warning("ACCOUNT_SCAN_IDENTITY_LOCK_PATCHED marker=%s", MARKER)
    return True


def _patch_loaded() -> bool:
    patched = False
    for name in (
        "bot.broker_manager", "broker_manager",
        "bot.broker_integration", "broker_integration",
        "bot.multi_account_broker_manager", "multi_account_broker_manager",
        "bot.nija_core_loop", "nija_core_loop",
    ):
        module = sys.modules.get(name)
        if not isinstance(module, ModuleType):
            continue
        patched = _patch_broker_classes(module) or patched
        patched = _patch_core_loop(module) or patched
    return patched


def _watchdog() -> None:
    deadline = time.monotonic() + max(30.0, float(os.getenv("NIJA_RUNTIME_PATCH_WATCHDOG_S", "180") or 180))
    while time.monotonic() < deadline:
        try:
            _patch_loaded()
        except Exception as exc:
            logger.debug("RUNTIME_CONVERGENCE_V2_RETRY marker=%s err=%s", MARKER, exc)
        time.sleep(0.25)


def install() -> None:
    global _STARTED
    with _LOCK:
        os.environ.setdefault("NIJA_ACCOUNT_EXIT_MANAGEMENT_INTERVAL_S", "5")
        os.environ.setdefault("NIJA_ACCOUNT_SCAN_LOCK_TIMEOUT_S", "0.25")
        for name in (
            "bot.broker_manager", "bot.broker_integration",
            "bot.multi_account_broker_manager", "bot.nija_core_loop",
        ):
            try:
                module = importlib.import_module(name)
                _patch_broker_classes(module)
                _patch_core_loop(module)
            except Exception as exc:
                logger.debug("RUNTIME_CONVERGENCE_V2_EAGER_IMPORT marker=%s module=%s err=%s", MARKER, name, exc)
        _patch_loaded()
        if not _STARTED:
            _STARTED = True
            threading.Thread(target=_watchdog, name="RuntimeConvergenceV2Watchdog", daemon=True).start()
        logger.warning("RUNTIME_CONVERGENCE_V2_INSTALLED marker=%s", MARKER)


def installed() -> bool:
    return _STARTED


__all__ = ["install", "installed", "_identity", "_patch_broker_classes", "_patch_core_loop", "_rebind_tracker"]
