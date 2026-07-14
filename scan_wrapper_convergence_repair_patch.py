"""Canonicalize NIJA scan wrappers without suppressing legitimate account scans.

Legacy runtime watchdogs independently wrapped ``NijaCoreLoop.run_scan_phase``.
The broker-slot wrapper from ``startup_runtime_safety`` did not expose
``__wrapped__`` and was not listed as a known wrapper.  The canonical wrapper
therefore captured that wrapper as its base; the broker-slot wrapper then called
back into the canonical method and every user cycle was returned as
``duplicate_scan_suppressed``.  This module unwraps both explicit
``__wrapped__`` chains and the legacy closure-held broker-slot base.

The authentication convergence watchdog also owns scan serialization.  It must
never be nested underneath this owner: two account locks using the same identity
on the same thread look like recursion and produce ``scored=0, blocked=1``.
The scan-owner marker is therefore treated as a known layer and collapsed before
this canonical owner is installed.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
import time
from types import ModuleType, SimpleNamespace
from typing import Any, Callable

logger = logging.getLogger("nija.scan_wrapper_convergence_repair")
_MARKER = "20260714a"
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
_WATCHDOG_STARTED = False
_SCAN_OWNER_GUARD_ATTR = "_nija_single_scan_owner_guard_20260714a"

_KNOWN_WRAPPER_MARKERS = (
    "_nija_account_scan_serialized_e",
    "_nija_final_result_contract_e",
    "_nija_account_scan_serialized",
    "_nija_final_result_contract",
    "_nija_scan_wrapper_canonical_h",
    "_nija_scan_wrapper_canonical_v2",
    "_nija_scan_owner_result_reuse_20260713b",
    "_nija_broker_slot_scoped",
)


def _duplicate_result(reason: str = "duplicate_scan_suppressed") -> SimpleNamespace:
    return SimpleNamespace(
        symbols_scored=0,
        entries_taken=0,
        entries_blocked=1,
        exits_taken=0,
        next_interval=max(5, int(float(os.getenv("NIJA_DUPLICATE_SCAN_NEXT_INTERVAL_S", "15") or 15))),
        errors=[reason],
        metadata={"duplicate_scan": True, "reason": reason},
    )


def _coerce_result(result: Any) -> Any:
    if result is None:
        return _duplicate_result("scan_returned_none")
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
    if not all(hasattr(result, field) for field in required):
        logger.error(
            "INVALID_SCAN_RESULT_REPLACED marker=%s result_type=%s",
            _MARKER,
            type(result).__name__,
        )
        return _duplicate_result("invalid_scan_result")
    return result


def _broker_identity(broker: Any, owner: Any = None) -> str:
    source = broker or owner
    account = ""
    for obj in (broker, owner):
        if obj is None:
            continue
        for attr in ("account_identifier", "account_id", "user_id", "account_name", "owner_id"):
            value = getattr(obj, attr, None)
            if value:
                account = str(value).strip().lower().replace(" ", "_")
                break
        if account:
            break
    if not account:
        if source is not None:
            account_type = getattr(source, "account_type", None)
            account = str(getattr(account_type, "value", account_type) or "platform").strip().lower()
        else:
            account = "platform"
    account = account or "platform"
    text_parts = []
    for attr in ("broker_type", "broker_name", "name", "exchange", "exchange_name"):
        try:
            value = getattr(source, attr, "") if source is not None else ""
            value = getattr(value, "value", value)
            text_parts.append(str(value or ""))
        except Exception:
            continue
    text = " ".join(text_parts).lower() + " " + (type(source).__name__.lower() if source is not None else "")
    venue = next((name for name in ("kraken", "coinbase", "okx", "alpaca", "binance") if name in text), "unknown")
    return f"{account}:{venue}"


def _is_known_wrapper(func: Callable[..., Any]) -> bool:
    return any(bool(getattr(func, marker, False)) for marker in _KNOWN_WRAPPER_MARKERS)


def _closure_wrapped(func: Callable[..., Any]) -> Callable[..., Any] | None:
    """Recover a wrapped function stored only in a legacy closure.

    ``startup_runtime_safety._run_scan_phase_broker_scoped`` captured
    ``original_run_scan_phase`` but did not set ``__wrapped__``. Inspecting the
    named free variable is safe and specific; arbitrary callable closure cells are
    never selected.
    """
    if not getattr(func, "_nija_broker_slot_scoped", False):
        return None
    try:
        freevars = tuple(getattr(func, "__code__").co_freevars)
        closure = tuple(getattr(func, "__closure__", ()) or ())
        mapping = {name: cell.cell_contents for name, cell in zip(freevars, closure)}
        candidate = mapping.get("original_run_scan_phase")
        return candidate if callable(candidate) else None
    except Exception:
        return None


def _next_wrapped(func: Callable[..., Any]) -> Callable[..., Any] | None:
    wrapped = getattr(func, "__wrapped__", None)
    if callable(wrapped):
        return wrapped
    return _closure_wrapped(func)


def _unwrap_known(func: Callable[..., Any]) -> tuple[Callable[..., Any], int, bool]:
    current = func
    seen: set[int] = set()
    depth = 0
    cycle = False
    while callable(current) and _is_known_wrapper(current):
        ident = id(current)
        if ident in seen:
            cycle = True
            break
        seen.add(ident)
        wrapped = _next_wrapped(current)
        if not callable(wrapped):
            break
        current = wrapped
        depth += 1
        if depth >= 4096:
            cycle = True
            break
    return current, depth, cycle


def _chain_has_current_owner(func: Callable[..., Any]) -> bool:
    current: Any = func
    seen: set[int] = set()
    for _ in range(256):
        if not callable(current) or id(current) in seen:
            break
        seen.add(id(current))
        if getattr(current, "_nija_scan_wrapper_release", "") == _MARKER:
            return True
        current = getattr(current, "__wrapped__", None)
    return False


def _guard_secondary_scan_owner() -> bool:
    """Prevent the auth convergence watchdog from installing a second owner."""
    guarded = False
    for module_name in ("scan_owner_okx_auth_convergence_patch", "nija.scan_owner_okx_auth_convergence_patch"):
        convergence = sys.modules.get(module_name)
        if not isinstance(convergence, ModuleType):
            continue
        patch_core = getattr(convergence, "_patch_core", None)
        if not callable(patch_core):
            continue
        if getattr(patch_core, _SCAN_OWNER_GUARD_ATTR, False):
            guarded = True
            continue
        original_patch_core = patch_core

        def guarded_patch_core(module: ModuleType, _original: Callable[..., Any] = original_patch_core) -> bool:
            cls = getattr(module, "NijaCoreLoop", None)
            method = getattr(cls, "run_scan_phase", None) if isinstance(cls, type) else None
            if callable(method) and _chain_has_current_owner(method):
                logger.debug(
                    "SCAN_OWNER_DELEGATED_TO_CANONICAL marker=%s module=%s",
                    _MARKER,
                    getattr(module, "__name__", "unknown"),
                )
                return True
            return bool(_original(module))

        setattr(guarded_patch_core, _SCAN_OWNER_GUARD_ATTR, True)
        setattr(guarded_patch_core, "__wrapped__", original_patch_core)
        setattr(convergence, "_patch_core", guarded_patch_core)
        logger.critical(
            "SECONDARY_SCAN_OWNER_GUARDED marker=%s module=%s canonical_owner=scan_wrapper_convergence",
            _MARKER,
            module_name,
        )
        guarded = True
    return guarded


def _patch_core_loop(module: ModuleType) -> bool:
    cls = getattr(module, "NijaCoreLoop", None)
    if not isinstance(cls, type):
        return False
    current = getattr(cls, "run_scan_phase", None)
    if not callable(current):
        return False
    if getattr(current, "_nija_scan_wrapper_release", "") == _MARKER:
        return False

    base, depth, cycle = _unwrap_known(current)
    if not callable(base):
        logger.critical("SCAN_WRAPPER_CANONICALIZATION_FAILED marker=%s reason=no_base", _MARKER)
        return False
    if cycle:
        logger.critical(
            "SCAN_WRAPPER_CYCLE_DETECTED marker=%s depth=%d action=replace_with_last_resolved_base",
            _MARKER,
            depth,
        )

    def run_scan_phase(self: Any, *args: Any, **kwargs: Any) -> Any:
        broker = (
            kwargs.get("broker")
            or getattr(self, "broker", None)
            or getattr(self, "broker_client", None)
            or getattr(self, "_broker", None)
            or (args[0] if args else None)
        )
        key = _broker_identity(broker, self)
        with _SCAN_STATES_GUARD:
            state = _SCAN_STATES.setdefault(key, ScanState())
        current_thread_id = threading.get_ident()

        if state.owner_thread_id == current_thread_id:
            recovered, recovered_depth, recovered_cycle = _unwrap_known(base)
            if callable(recovered) and recovered is not base and not recovered_cycle:
                logger.critical(
                    "SCAN_REENTRANT_WRAPPER_RECOVERED marker=%s identity=%s removed_layers=%d",
                    _MARKER,
                    key,
                    recovered_depth,
                )
                return _coerce_result(recovered(self, *args, **kwargs))
            logger.error(
                "REENTRANT_SCAN_SUPPRESSED marker=%s identity=%s reason=true_recursive_call",
                _MARKER,
                key,
            )
            return _duplicate_result("true_recursive_scan_suppressed")

        owner_timeout = max(0.1, float(os.getenv("NIJA_ACCOUNT_SCAN_LOCK_TIMEOUT_S", "1.0") or 1.0))
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

        wait_timeout = max(5.0, float(os.getenv("NIJA_DUPLICATE_SCAN_RESULT_WAIT_S", "45") or 45))
        if state.complete.wait(timeout=wait_timeout) and state.result is not None:
            logger.info("DUPLICATE_SCAN_RESULT_REUSED marker=%s identity=%s", _MARKER, key)
            return state.result
        logger.error(
            "SCAN_OWNER_TIMEOUT marker=%s identity=%s owner_thread=%s age_s=%.2f",
            _MARKER,
            key,
            state.owner_thread_id,
            max(0.0, time.monotonic() - state.started_at),
        )
        return _duplicate_result("scan_owner_timeout")

    run_scan_phase._nija_scan_wrapper_canonical_h = True  # type: ignore[attr-defined]
    run_scan_phase._nija_scan_wrapper_canonical_v2 = True  # type: ignore[attr-defined]
    run_scan_phase._nija_account_scan_serialized_e = True  # type: ignore[attr-defined]
    run_scan_phase._nija_final_result_contract_e = True  # type: ignore[attr-defined]
    run_scan_phase._nija_account_scan_serialized = True  # type: ignore[attr-defined]
    run_scan_phase._nija_final_result_contract = True  # type: ignore[attr-defined]
    run_scan_phase._nija_scan_wrapper_release = _MARKER  # type: ignore[attr-defined]
    run_scan_phase.__wrapped__ = base  # type: ignore[attr-defined]
    setattr(cls, "run_scan_phase", run_scan_phase)
    logger.critical(
        "SCAN_WRAPPER_CANONICALIZED marker=%s removed_layers=%d cycle_detected=%s base=%s broker_slot_unwrap=true single_owner=true",
        _MARKER,
        depth,
        str(cycle).lower(),
        getattr(base, "__qualname__", getattr(base, "__name__", "unknown")),
    )
    return True


def _patch_loaded() -> bool:
    changed = _guard_secondary_scan_owner()
    for name in ("bot.nija_core_loop", "nija_core_loop"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            changed = _patch_core_loop(module) or changed
    return changed


def _watchdog() -> None:
    deadline = time.monotonic() + max(60.0, float(os.getenv("NIJA_SCAN_CANONICAL_WATCHDOG_S", "600") or 600))
    while time.monotonic() < deadline:
        try:
            _patch_loaded()
        except Exception as exc:
            logger.error("SCAN_WRAPPER_CONVERGENCE_RETRY marker=%s error=%s", _MARKER, exc)
        time.sleep(0.25)


def install() -> bool:
    global _WATCHDOG_STARTED
    with _LOCK:
        _guard_secondary_scan_owner()
        _patch_loaded()
        if not _WATCHDOG_STARTED:
            _WATCHDOG_STARTED = True
            threading.Thread(target=_watchdog, name="ScanWrapperCanonicalWatchdog", daemon=True).start()
        os.environ["NIJA_SCAN_WRAPPER_CONVERGENCE_REPAIR_INSTALLED"] = "1"
        os.environ["NIJA_SCAN_WRAPPER_RELEASE"] = _MARKER
        logger.critical("SCAN_WRAPPER_CONVERGENCE_REPAIR_INSTALLED marker=%s single_owner=true", _MARKER)
        return True


__all__ = [
    "install",
    "_coerce_result",
    "_unwrap_known",
    "_closure_wrapped",
    "_patch_core_loop",
    "_broker_identity",
]
