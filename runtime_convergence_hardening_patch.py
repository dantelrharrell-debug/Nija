"""Harden NIJA runtime convergence without bypassing broker or risk controls.

Repairs production-only failure modes observed in July 2026 logs:
* auth recovery attached to only one broker module;
* duplicate platform/user workers and duplicate account recovery supervisors;
* concurrent scans for the same account/broker;
* stale zero-signal streak values (for example 999);
* shared position-tracker files across account identities.

The guard never fabricates authentication, balances, broker acknowledgements, fills,
or profitability. Existing writer-authority, risk, exchange and exit controls remain
fully authoritative.
"""
from __future__ import annotations

import importlib
import logging
import os
import sys
import threading
from pathlib import Path
from types import ModuleType
from typing import Any, Callable, Optional

logger = logging.getLogger("nija.runtime_convergence")
_MARKER = "20260712a"
_LOCK = threading.RLock()
_ORIGINAL_IMPORT: Optional[Callable[..., Any]] = None
_PATCHED_MODULES: set[str] = set()
_WORKER_REGISTRY: dict[str, threading.Thread] = {}
_WORKER_LOCK = threading.RLock()
_SCAN_LOCKS: dict[str, threading.RLock] = {}
_SCAN_LOCKS_GUARD = threading.RLock()


def _clean(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "_")


def _broker_name(obj: Any) -> str:
    text = " ".join(
        str(getattr(obj, attr, "") or "")
        for attr in ("broker_type", "broker_name", "name", "exchange", "exchange_name")
    ).lower()
    text += " " + type(obj).__name__.lower()
    for name in ("kraken", "coinbase", "okx", "alpaca", "binance"):
        if name in text:
            return name
    return "unknown"


def _account_identity(obj: Any) -> str:
    for attr in ("account_id", "user_id", "account_name", "owner_id"):
        value = getattr(obj, attr, None)
        if value:
            return _clean(value)
    account_type = getattr(obj, "account_type", None)
    value = getattr(account_type, "value", account_type)
    if value:
        return _clean(value)
    return "platform"


def _broker_identity(obj: Any) -> str:
    return f"{_account_identity(obj)}:{_broker_name(obj)}"


def _patch_auth_surface(module: ModuleType) -> bool:
    """Attach existing auth normalization to every Coinbase/OKX broker surface."""
    try:
        auth = importlib.import_module("broker_auth_recovery_patch")
    except Exception as exc:
        logger.warning("RUNTIME_CONVERGENCE_AUTH_IMPORT_FAILED marker=%s err=%s", _MARKER, exc)
        return False

    patched = False
    for attr_name in dir(module):
        cls = getattr(module, attr_name, None)
        if not isinstance(cls, type):
            continue
        lowered = attr_name.lower()
        venue = "coinbase" if "coinbase" in lowered else "okx" if "okx" in lowered else ""
        if not venue:
            continue
        for method_name in ("connect", "verify_connection", "test_connection"):
            original = getattr(cls, method_name, None)
            if not callable(original) or getattr(original, "_nija_runtime_convergence_auth", False):
                continue

            def wrapped(self: Any, *args: Any, __original: Callable[..., Any] = original,
                        __venue: str = venue, **kwargs: Any) -> Any:
                if __venue == "coinbase":
                    auth.normalize_coinbase_environment()
                else:
                    auth.normalize_okx_environment()
                return __original(self, *args, **kwargs)

            wrapped._nija_runtime_convergence_auth = True  # type: ignore[attr-defined]
            wrapped.__wrapped__ = original  # type: ignore[attr-defined]
            setattr(cls, method_name, wrapped)
            patched = True
            logger.warning(
                "RUNTIME_AUTH_SURFACE_PATCHED marker=%s module=%s class=%s method=%s venue=%s",
                _MARKER, getattr(module, "__name__", "unknown"), attr_name, method_name, venue,
            )
    return patched


def _wrap_thread_start_method(cls: type, method_name: str) -> bool:
    original = getattr(cls, method_name, None)
    if not callable(original) or getattr(original, "_nija_runtime_worker_dedupe", False):
        return False

    def wrapped(self: Any, *args: Any, **kwargs: Any) -> Any:
        broker = kwargs.get("broker")
        if broker is None:
            broker = next((arg for arg in args if _broker_name(arg) != "unknown"), None)
        user_id = kwargs.get("user_id") or kwargs.get("account_id")
        broker_key = _broker_identity(broker) if broker is not None else "unknown:unknown"
        if user_id:
            broker_key = f"{_clean(user_id)}:{broker_key.split(':')[-1]}"
        key = f"{type(self).__name__}:{method_name}:{broker_key}"
        with _WORKER_LOCK:
            existing = _WORKER_REGISTRY.get(key)
            if existing is not None and existing.is_alive():
                logger.warning("DUPLICATE_WORKER_SUPPRESSED marker=%s key=%s thread=%s", _MARKER, key, existing.name)
                return existing
        result = original(self, *args, **kwargs)
        candidate = result if isinstance(result, threading.Thread) else None
        if candidate is None:
            for mapping_name in ("broker_threads", "user_broker_threads"):
                mapping = getattr(self, mapping_name, None)
                if isinstance(mapping, dict):
                    values = list(mapping.values())
                    while values:
                        value = values.pop()
                        if isinstance(value, threading.Thread) and value.is_alive():
                            candidate = value
                            break
                        if isinstance(value, dict):
                            values.extend(value.values())
                    if candidate is not None:
                        break
        if candidate is not None:
            with _WORKER_LOCK:
                _WORKER_REGISTRY[key] = candidate
        return result

    wrapped._nija_runtime_worker_dedupe = True  # type: ignore[attr-defined]
    wrapped.__wrapped__ = original  # type: ignore[attr-defined]
    setattr(cls, method_name, wrapped)
    logger.warning("WORKER_START_DEDUPE_PATCHED marker=%s class=%s method=%s", _MARKER, cls.__name__, method_name)
    return True


def _patch_independent_trader(module: ModuleType) -> bool:
    cls = getattr(module, "IndependentBrokerTrader", None)
    if not isinstance(cls, type):
        return False
    patched = False
    for name in (
        "start_independent_trading", "_start_broker_thread", "_start_trading_thread",
        "_start_user_broker_thread", "_start_user_trading_thread", "_start_exit_only_thread",
        "_start_connection_monitor",
    ):
        patched = _wrap_thread_start_method(cls, name) or patched
    return patched


def _scan_key(core: Any, broker: Any) -> str:
    return f"{id(core)}:{_broker_identity(broker)}"


def _patch_core_loop(module: ModuleType) -> bool:
    cls = getattr(module, "NijaCoreLoop", None)
    if not isinstance(cls, type):
        return False
    patched = False

    original_phase3 = getattr(cls, "_phase3_scan_and_enter", None)
    if callable(original_phase3) and not getattr(original_phase3, "_nija_zero_streak_cap", False):
        def phase3(self: Any, broker: Any, snapshot: Any, symbols: Any, available_slots: Any,
                   zero_signal_streak: int = 0, *args: Any, **kwargs: Any) -> Any:
            cap = max(0, int(float(os.getenv("NIJA_ZERO_SIGNAL_STREAK_CAP", "12") or 12)))
            raw = int(zero_signal_streak or 0)
            bounded = min(max(raw, 0), cap)
            if bounded != raw:
                logger.warning("ZERO_SIGNAL_STREAK_REPAIRED marker=%s raw=%d bounded=%d", _MARKER, raw, bounded)
            return original_phase3(self, broker, snapshot, symbols, available_slots, bounded, *args, **kwargs)
        phase3._nija_zero_streak_cap = True  # type: ignore[attr-defined]
        phase3.__wrapped__ = original_phase3  # type: ignore[attr-defined]
        setattr(cls, "_phase3_scan_and_enter", phase3)
        patched = True

    original_scan = getattr(cls, "run_scan_phase", None)
    if callable(original_scan) and not getattr(original_scan, "_nija_account_scan_serialized", False):
        def run_scan_phase(self: Any, *args: Any, **kwargs: Any) -> Any:
            broker = kwargs.get("broker") or (args[0] if args else None)
            key = _scan_key(self, broker)
            with _SCAN_LOCKS_GUARD:
                lock = _SCAN_LOCKS.setdefault(key, threading.RLock())
            timeout = max(1.0, float(os.getenv("NIJA_ACCOUNT_SCAN_LOCK_TIMEOUT_S", "5") or 5))
            if not lock.acquire(timeout=timeout):
                logger.error("DUPLICATE_SCAN_BLOCKED marker=%s key=%s timeout_s=%.1f", _MARKER, key, timeout)
                return None
            try:
                return original_scan(self, *args, **kwargs)
            finally:
                lock.release()
        run_scan_phase._nija_account_scan_serialized = True  # type: ignore[attr-defined]
        run_scan_phase.__wrapped__ = original_scan  # type: ignore[attr-defined]
        setattr(cls, "run_scan_phase", run_scan_phase)
        patched = True
    return patched


def _scope_position_path(instance: Any) -> None:
    identity = _broker_identity(instance).replace(":", "_")
    base = os.getenv("NIJA_POSITION_STATE_DIR", "data")
    scoped = str(Path(base) / f"positions_{identity}.json")
    for attr in ("positions_file", "position_file", "state_file", "storage_path", "file_path"):
        if hasattr(instance, attr):
            try:
                current = str(getattr(instance, attr, "") or "")
                if current.endswith("positions.json") or not current:
                    setattr(instance, attr, scoped)
                    logger.warning("POSITION_STATE_SCOPED marker=%s identity=%s path=%s", _MARKER, identity, scoped)
            except Exception:
                pass


def _patch_position_tracker(module: ModuleType) -> bool:
    patched = False
    for attr_name in dir(module):
        cls = getattr(module, attr_name, None)
        if not isinstance(cls, type) or "positiontracker" not in attr_name.lower():
            continue
        original = getattr(cls, "__init__", None)
        if not callable(original) or getattr(original, "_nija_position_scope", False):
            continue
        def init(self: Any, *args: Any, __original: Callable[..., Any] = original, **kwargs: Any) -> None:
            __original(self, *args, **kwargs)
            _scope_position_path(self)
        init._nija_position_scope = True  # type: ignore[attr-defined]
        init.__wrapped__ = original  # type: ignore[attr-defined]
        setattr(cls, "__init__", init)
        patched = True
    return patched


def _patch_module(module: ModuleType) -> bool:
    name = str(getattr(module, "__name__", ""))
    patched = _patch_auth_surface(module)
    if name.endswith("independent_broker_trader"):
        patched = _patch_independent_trader(module) or patched
    if name.endswith("nija_core_loop"):
        patched = _patch_core_loop(module) or patched
    if "position" in name:
        patched = _patch_position_tracker(module) or patched
    if patched:
        _PATCHED_MODULES.add(name)
    return patched


def _try_loaded() -> bool:
    patched = False
    for name, module in list(sys.modules.items()):
        if not isinstance(module, ModuleType):
            continue
        if name in {
            "bot.broker_manager", "broker_manager", "bot.broker_integration", "broker_integration",
            "bot.multi_account_broker_manager", "multi_account_broker_manager",
            "bot.independent_broker_trader", "independent_broker_trader",
            "bot.nija_core_loop", "nija_core_loop", "bot.position_tracker", "position_tracker",
        }:
            patched = _patch_module(module) or patched
    return patched


def install() -> None:
    global _ORIGINAL_IMPORT
    with _LOCK:
        _try_loaded()
        if _ORIGINAL_IMPORT is not None:
            return
        _ORIGINAL_IMPORT = importlib.import_module
        def wrapped(name: str, package: str | None = None):
            module = _ORIGINAL_IMPORT(name, package)  # type: ignore[misc]
            _patch_module(module)
            return module
        importlib.import_module = wrapped  # type: ignore[assignment]
        logger.warning("RUNTIME_CONVERGENCE_HARDENING_INSTALL_REQUESTED marker=%s", _MARKER)


def installed() -> bool:
    return bool(_PATCHED_MODULES)


__all__ = ["install", "installed", "_broker_identity", "_patch_module"]
