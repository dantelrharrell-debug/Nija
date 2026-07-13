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
from types import ModuleType, SimpleNamespace
from typing import Any, Callable

logger = logging.getLogger("nija.runtime_convergence_v2")
MARKER = "20260712e"
_LOCK = threading.RLock()


class ScanState:
    """Per-account scan state used to coordinate concurrent scan requests."""

    __slots__ = ("lock", "complete", "result", "owner_thread_id", "started_at")

    def __init__(self) -> None:
        self.lock: threading.Lock = threading.Lock()
        self.complete: threading.Event = threading.Event()
        self.result: Any = None
        self.owner_thread_id: int | None = None
        self.started_at: float = 0.0


_SCAN_STATES: dict[str, ScanState] = {}
_SCAN_STATES_GUARD = threading.RLock()
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


def _identity(obj: Any, owner: Any = None) -> str:
    account = _account_id(obj)
    if account == "platform" and owner is not None:
        account = _account_id(owner)
    venue = _broker_name(obj) if obj is not None else _broker_name(owner)
    identity = f"{account}:{venue}"
    if identity == "platform:unknown":
        ref = obj if obj is not None else owner
        identity = f"platform:unknown:{id(ref) if ref is not None else 0}"
    return identity


def _auth_module() -> ModuleType | None:
    module = sys.modules.get("broker_auth_recovery_patch")
    return module if isinstance(module, ModuleType) else None


def _normalize_auth(venue: str) -> None:
    auth = _auth_module()
    if auth is None:
        logger.debug("RUNTIME_CONVERGENCE_V2_AUTH_DEFERRED marker=%s venue=%s", MARKER, venue)
        return
    normalizer = getattr(auth, f"normalize_{venue}_environment", None)
    if callable(normalizer):
        normalizer()


def _duplicate_result() -> SimpleNamespace:
    return SimpleNamespace(
        symbols_scored=0,
        entries_taken=0,
        entries_blocked=1,
        exits_taken=0,
        next_interval=max(5, int(float(os.getenv("NIJA_DUPLICATE_SCAN_NEXT_INTERVAL_S", "15") or 15))),
        errors=["duplicate_scan_suppressed"],
        metadata={"duplicate_scan": True},
    )


def _coerce_result(result: Any) -> Any:
    if result is None:
        return _duplicate_result()
    if isinstance(result, tuple):
        scored = int(result[0] or 0) if len(result) > 0 else 0
        blocked = int(result[1] or 0) if len(result) > 1 else 0
        entered = int(result[2] or 0) if len(result) > 2 else 0
        meta = result[3] if len(result) > 3 and isinstance(result[3], dict) else {}
        return SimpleNamespace(
            symbols_scored=scored,
            entries_taken=entered,
            entries_blocked=blocked,
            exits_taken=int(meta.get("exits_taken", 0) or 0),
            next_interval=int(meta.get("next_interval", 15) or 15),
            errors=list(meta.get("errors", [])),
            metadata=meta,
        )
    required = ("symbols_scored", "entries_taken", "entries_blocked", "exits_taken", "next_interval")
    if not all(hasattr(result, f) for f in required):
        logger.error(
            "INVALID_SCAN_RESULT_REPLACED marker=%s result_type=%s",
            MARKER,
            type(result).__name__,
        )
        return _duplicate_result()
    return result


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

    base = original

    def run_scan_phase(self: Any, *args: Any, **kwargs: Any) -> Any:
        broker = (
            kwargs.get("broker")
            or getattr(self, "broker", None)
            or getattr(self, "broker_client", None)
            or getattr(self, "_broker", None)
            or (args[0] if args else None)
        )
        key = _identity(broker, self)

        with _SCAN_STATES_GUARD:
            state = _SCAN_STATES.setdefault(key, ScanState())

        current_thread_id = threading.get_ident()

        # Prevent accidental recursive calls from the same scan owner.
        if state.owner_thread_id == current_thread_id:
            logger.error(
                "REENTRANT_SCAN_SUPPRESSED marker=%s identity=%s",
                MARKER,
                key,
            )
            return _duplicate_result()

        owner_timeout = max(
            0.1,
            float(os.getenv("NIJA_ACCOUNT_SCAN_LOCK_TIMEOUT_S", "1.0") or 1.0),
        )

        # Become the authoritative scan owner.
        if state.lock.acquire(timeout=owner_timeout):
            try:
                state.owner_thread_id = current_thread_id
                state.started_at = time.monotonic()
                state.complete.clear()

                result = _coerce_result(base(self, *args, **kwargs))
                state.result = result
                return result
            finally:
                state.owner_thread_id = None
                state.complete.set()
                state.lock.release()

        # Another legitimate scan is active.
        # Wait for it and reuse its result rather than reporting a blocked cycle.
        wait_timeout = max(
            5.0,
            float(os.getenv("NIJA_DUPLICATE_SCAN_RESULT_WAIT_S", "45") or 45),
        )

        if state.complete.wait(timeout=wait_timeout) and state.result is not None:
            logger.info(
                "DUPLICATE_SCAN_RESULT_REUSED marker=%s identity=%s",
                MARKER,
                key,
            )
            return state.result

        # The owner appears stalled. Fail closed without crashing or pretending
        # that the strategy evaluated the market.
        logger.error(
            "SCAN_OWNER_TIMEOUT marker=%s identity=%s owner_thread=%s age_s=%.2f",
            MARKER,
            key,
            state.owner_thread_id,
            max(0.0, time.monotonic() - state.started_at),
        )
        return _duplicate_result()

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
        os.environ.setdefault("NIJA_ACCOUNT_SCAN_LOCK_TIMEOUT_S", "1")
        # Eager imports are safe here because this module never replaces importlib.import_module.
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


__all__ = [
    "install", "installed", "_identity", "_patch_broker_classes", "_patch_core_loop",
    "_rebind_tracker", "_duplicate_result", "_coerce_result", "_SCAN_STATES",
]
