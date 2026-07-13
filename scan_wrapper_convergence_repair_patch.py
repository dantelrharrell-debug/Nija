"""Canonicalize NIJA scan wrappers to prevent recursive wrapper stacking.

Legacy runtime watchdogs independently wrapped ``NijaCoreLoop.run_scan_phase``.
Each wrapper only recognized its own marker, so the watchdogs alternated wrappers
until calls exceeded Python's recursion limit. This repair unwraps known NIJA
scan wrappers to the original implementation and installs one canonical wrapper
that provides both account serialization and the required result contract.
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
_MARKER = "20260712h"
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

_KNOWN_WRAPPER_MARKERS = (
    "_nija_account_scan_serialized_e",
    "_nija_final_result_contract_e",
    "_nija_account_scan_serialized",
    "_nija_final_result_contract",
    "_nija_scan_wrapper_canonical_h",
)


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
    if not all(hasattr(result, field) for field in required):
        logger.error(
            "INVALID_SCAN_RESULT_REPLACED marker=%s result_type=%s",
            _MARKER,
            type(result).__name__,
        )
        return _duplicate_result()
    return result


def _broker_identity(broker: Any, owner: Any = None) -> str:
    source = broker or owner

    account = ""
    for obj in (broker, owner):
        if obj is None:
            continue
        for attr in ("account_id", "user_id", "account_name", "owner_id"):
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

    if not account:
        account = "platform"

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
        wrapped = getattr(current, "__wrapped__", None)
        if not callable(wrapped):
            break
        current = wrapped
        depth += 1
        if depth >= 4096:
            cycle = True
            break
    return current, depth, cycle


def _patch_core_loop(module: ModuleType) -> bool:
    cls = getattr(module, "NijaCoreLoop", None)
    if not isinstance(cls, type):
        return False
    current = getattr(cls, "run_scan_phase", None)
    if not callable(current):
        return False
    if getattr(current, "_nija_scan_wrapper_canonical_h", False):
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

        # Prevent accidental recursive calls from the same scan owner.
        if state.owner_thread_id == current_thread_id:
            logger.error(
                "REENTRANT_SCAN_SUPPRESSED marker=%s identity=%s",
                _MARKER,
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
                _MARKER,
                key,
            )
            return state.result

        # The owner appears stalled. Fail closed without crashing or pretending
        # that the strategy evaluated the market.
        logger.error(
            "SCAN_OWNER_TIMEOUT marker=%s identity=%s owner_thread=%s age_s=%.2f",
            _MARKER,
            key,
            state.owner_thread_id,
            max(0.0, time.monotonic() - state.started_at),
        )
        return _duplicate_result()

    # Satisfy every legacy watchdog so no older patch wraps this function again.
    run_scan_phase._nija_scan_wrapper_canonical_h = True  # type: ignore[attr-defined]
    run_scan_phase._nija_account_scan_serialized_e = True  # type: ignore[attr-defined]
    run_scan_phase._nija_final_result_contract_e = True  # type: ignore[attr-defined]
    run_scan_phase._nija_account_scan_serialized = True  # type: ignore[attr-defined]
    run_scan_phase._nija_final_result_contract = True  # type: ignore[attr-defined]
    run_scan_phase.__wrapped__ = base  # type: ignore[attr-defined]
    setattr(cls, "run_scan_phase", run_scan_phase)
    logger.critical(
        "SCAN_WRAPPER_CANONICALIZED marker=%s removed_layers=%d cycle_detected=%s base=%s",
        _MARKER,
        depth,
        str(cycle).lower(),
        getattr(base, "__qualname__", getattr(base, "__name__", "unknown")),
    )
    return True


def _patch_loaded() -> bool:
    changed = False
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
        _patch_loaded()
        if not _WATCHDOG_STARTED:
            _WATCHDOG_STARTED = True
            threading.Thread(target=_watchdog, name="ScanWrapperCanonicalWatchdog", daemon=True).start()
        os.environ["NIJA_SCAN_WRAPPER_CONVERGENCE_REPAIR_INSTALLED"] = "1"
        logger.critical("SCAN_WRAPPER_CONVERGENCE_REPAIR_INSTALLED marker=%s", _MARKER)
        return True


__all__ = ["install", "_coerce_result", "_unwrap_known", "_patch_core_loop", "_broker_identity"]
