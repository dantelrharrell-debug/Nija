"""Harden NIJA runtime convergence without global import-hook recursion.

Repairs auth attachment, duplicate workers/scans, stale signal streaks, and
account-scoped position state while preserving writer authority, broker
authentication, risk controls, exchange validation, and exit protections.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
import time
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, Callable

logger = logging.getLogger("nija.runtime_convergence")
_MARKER = "20260712e"
_LOCK = threading.RLock()
_PATCHED_MODULES: set[str] = set()
_WORKER_REGISTRY: dict[str, threading.Thread] = {}
_WORKER_LOCK = threading.RLock()
_SCAN_LOCKS: dict[str, threading.RLock] = {}
_SCAN_LOCKS_GUARD = threading.RLock()
_WATCHDOG_STARTED = False
# Kept for compatibility with the final repair. No global wrapper is installed.
_ORIGINAL_IMPORT = None


def _clean(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "_")


def _broker_name(obj: Any) -> str:
    text = " ".join(
        str(getattr(obj, attr, "") or "")
        for attr in ("broker_type", "broker_name", "name", "exchange", "exchange_name")
    ).lower() + " " + type(obj).__name__.lower()
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
    return _clean(value) if value else "platform"


def _broker_identity(obj: Any) -> str:
    return f"{_account_identity(obj)}:{_broker_name(obj)}"


def _auth_module() -> ModuleType | None:
    module = sys.modules.get("broker_auth_recovery_patch")
    return module if isinstance(module, ModuleType) else None


def _patch_auth_surface(module: ModuleType) -> bool:
    auth = _auth_module()
    if auth is None:
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
            if not callable(original) or getattr(original, "_nija_runtime_convergence_auth_e", False):
                continue

            def wrapped(self: Any, *args: Any, __original: Callable[..., Any] = original,
                        __venue: str = venue, **kwargs: Any) -> Any:
                normalizer = getattr(auth, f"normalize_{__venue}_environment", None)
                if callable(normalizer):
                    normalizer()
                return __original(self, *args, **kwargs)

            wrapped._nija_runtime_convergence_auth_e = True  # type: ignore[attr-defined]
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
    if not callable(original) or getattr(original, "_nija_runtime_worker_dedupe_e", False):
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
                    stack = list(mapping.values())
                    while stack:
                        value = stack.pop()
                        if isinstance(value, threading.Thread) and value.is_alive():
                            candidate = value
                            break
                        if isinstance(value, dict):
                            stack.extend(value.values())
                    if candidate is not None:
                        break
        if candidate is not None:
            with _WORKER_LOCK:
                _WORKER_REGISTRY[key] = candidate
        return result

    wrapped._nija_runtime_worker_dedupe_e = True  # type: ignore[attr-defined]
    wrapped.__wrapped__ = original  # type: ignore[attr-defined]
    setattr(cls, method_name, wrapped)
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


def _duplicate_result() -> SimpleNamespace:
    return SimpleNamespace(
        symbols_scored=0, entries_taken=0, entries_blocked=1, exits_taken=0,
        next_interval=max(5, int(float(os.getenv("NIJA_DUPLICATE_SCAN_NEXT_INTERVAL_S", "15") or 15))),
        errors=["duplicate_scan_suppressed"], metadata={"duplicate_scan": True},
    )


def _patch_core_loop(module: ModuleType) -> bool:
    cls = getattr(module, "NijaCoreLoop", None)
    if not isinstance(cls, type):
        return False
    patched = False
    original_phase3 = getattr(cls, "_phase3_scan_and_enter", None)
    if callable(original_phase3) and not getattr(original_phase3, "_nija_zero_streak_cap_e", False):
        def phase3(self: Any, broker: Any, snapshot: Any, symbols: Any, available_slots: Any,
                   zero_signal_streak: int = 0, *args: Any, **kwargs: Any) -> Any:
            cap = max(0, int(float(os.getenv("NIJA_ZERO_SIGNAL_STREAK_CAP", "12") or 12)))
            raw = int(zero_signal_streak or 0)
            bounded = min(max(raw, 0), cap)
            if bounded != raw:
                logger.warning("ZERO_SIGNAL_STREAK_REPAIRED marker=%s raw=%d bounded=%d", _MARKER, raw, bounded)
            return original_phase3(self, broker, snapshot, symbols, available_slots, bounded, *args, **kwargs)
        phase3._nija_zero_streak_cap_e = True  # type: ignore[attr-defined]
        phase3.__wrapped__ = original_phase3  # type: ignore[attr-defined]
        setattr(cls, "_phase3_scan_and_enter", phase3)
        patched = True

    original_scan = getattr(cls, "run_scan_phase", None)
    if callable(original_scan) and not getattr(original_scan, "_nija_account_scan_serialized_e", False):
        def run_scan_phase(self: Any, *args: Any, **kwargs: Any) -> Any:
            broker = kwargs.get("broker") or (args[0] if args else None)
            key = _broker_identity(broker)
            with _SCAN_LOCKS_GUARD:
                lock = _SCAN_LOCKS.setdefault(key, threading.RLock())
            timeout = max(0.01, float(os.getenv("NIJA_ACCOUNT_SCAN_LOCK_TIMEOUT_S", "0.25") or 0.25))
            if not lock.acquire(timeout=timeout):
                logger.critical("DUPLICATE_SCAN_BLOCKED marker=%s key=%s timeout_s=%.2f", _MARKER, key, timeout)
                return _duplicate_result()
            try:
                result = original_scan(self, *args, **kwargs)
                return _duplicate_result() if result is None else result
            finally:
                lock.release()
        run_scan_phase._nija_account_scan_serialized_e = True  # type: ignore[attr-defined]
        run_scan_phase.__wrapped__ = original_scan  # type: ignore[attr-defined]
        setattr(cls, "run_scan_phase", run_scan_phase)
        patched = True
    return patched


def _scope_position_path(instance: Any) -> None:
    identity = _broker_identity(instance).replace(":", "_")
    scoped = str(Path(os.getenv("NIJA_POSITION_STATE_DIR", "data")) / f"positions_{identity}.json")
    for attr in ("positions_file", "position_file", "state_file", "storage_path", "file_path"):
        if hasattr(instance, attr):
            try:
                current = str(getattr(instance, attr, "") or "")
                if current.endswith("positions.json") or not current:
                    setattr(instance, attr, scoped)
            except Exception:
                pass


def _patch_position_tracker(module: ModuleType) -> bool:
    patched = False
    for attr_name in dir(module):
        cls = getattr(module, attr_name, None)
        if not isinstance(cls, type) or "positiontracker" not in attr_name.lower():
            continue
        original = getattr(cls, "__init__", None)
        if not callable(original) or getattr(original, "_nija_position_scope_e", False):
            continue
        def init(self: Any, *args: Any, __original: Callable[..., Any] = original, **kwargs: Any) -> None:
            __original(self, *args, **kwargs)
            _scope_position_path(self)
        init._nija_position_scope_e = True  # type: ignore[attr-defined]
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
    targets = {
        "bot.broker_manager", "broker_manager", "bot.broker_integration", "broker_integration",
        "bot.multi_account_broker_manager", "multi_account_broker_manager",
        "bot.independent_broker_trader", "independent_broker_trader",
        "bot.nija_core_loop", "nija_core_loop", "bot.position_tracker", "position_tracker",
    }
    for name, module in list(sys.modules.items()):
        if name in targets and isinstance(module, ModuleType):
            patched = _patch_module(module) or patched
    return patched


def _watchdog() -> None:
    deadline = time.monotonic() + max(60.0, float(os.getenv("NIJA_RUNTIME_PATCH_WATCHDOG_S", "600") or 600))
    while time.monotonic() < deadline:
        try:
            _try_loaded()
        except Exception as exc:
            logger.debug("RUNTIME_CONVERGENCE_RETRY marker=%s err=%s", _MARKER, exc)
        time.sleep(0.25)


def install() -> None:
    global _WATCHDOG_STARTED
    with _LOCK:
        _try_loaded()
        if not _WATCHDOG_STARTED:
            _WATCHDOG_STARTED = True
            threading.Thread(target=_watchdog, name="RuntimeConvergenceWatchdog", daemon=True).start()
        logger.warning("RUNTIME_CONVERGENCE_HARDENING_INSTALLED marker=%s import_hook=false", _MARKER)


def installed() -> bool:
    return _WATCHDOG_STARTED


__all__ = ["install", "installed", "_broker_identity", "_patch_module", "_duplicate_result"]
