"""Universal exit canonical broker rebinding v331.

The universal exit supervisor registers broker objects very early. During
writer-first startup a pre-bootstrap platform broker can be registered before the
canonical multi-account object. The legacy duplicate rule keeps the first object
when the logical identity and class match, even if a later object owns the fresh
v285 authoritative position snapshot. The scanner can therefore run against an
empty/stale tracker while reconciliation correctly proves a real held position.

v331 makes duplicate handling provenance-aware. For one logical account/venue it
prefers, in order:
  * a fresher genuine v285 authoritative snapshot;
  * a broker with current tracker positions;
  * a connected broker over a disconnected broker.
Equal evidence keeps the existing object to avoid oscillation. Rebinding mutates
only the supervisor's in-process object registry. It never mutates broker state,
position state, balances, orders, fills, cost basis, readiness, or risk gates.
"""
from __future__ import annotations

import builtins
import importlib
import logging
import os
import threading
import time
from functools import wraps
from types import ModuleType
from typing import Any, Mapping

LOGGER = logging.getLogger("nija.runtime_universal_exit_broker_rebinding_v331")
MARKER = "20260831-universal-exit-broker-rebinding-v331"
RELEASE_ID = "20260831-runtime-convergence-v331"
_READY_FLAG = "NIJA_RUNTIME_UNIVERSAL_EXIT_BROKER_REBINDING_V331_READY"
_PATCH_ATTR = "_nija_universal_exit_broker_rebinding_v331"
_INSTALL_FLAG = "_NIJA_RUNTIME_UNIVERSAL_EXIT_BROKER_REBINDING_V331"
_LOCK = threading.RLock()


def _f(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
        return result if result == result else default
    except Exception:
        return default


def _connected(broker: Any) -> bool:
    for attr in ("connected", "is_connected", "_connected"):
        value = getattr(broker, attr, None)
        if isinstance(value, bool):
            return value
        if callable(value):
            try:
                result = value()
            except Exception:
                continue
            if isinstance(result, bool):
                return result
    status = str(getattr(broker, "status", "") or "").strip().lower()
    return status in {"connected", "ready", "online", "active"}


def _tracker_count(broker: Any) -> int:
    tracker = getattr(broker, "position_tracker", None)
    if tracker is None:
        return 0
    getter = getattr(tracker, "get_all_positions", None)
    if not callable(getter):
        getter = getattr(tracker, "get_open_positions", None)
    if not callable(getter):
        return 0
    try:
        rows = getter() or []
    except Exception:
        return 0
    if isinstance(rows, Mapping):
        return len(rows)
    try:
        return len(rows)
    except Exception:
        try:
            return len(tuple(rows))
        except Exception:
            return 0


def _v285_evidence(broker: Any) -> tuple[bool, float, int]:
    at = _f(getattr(broker, "_nija_authoritative_position_snapshot_at_monotonic_v285", 0.0))
    if at <= 0.0:
        return False, float("inf"), 0
    age = max(0.0, time.monotonic() - at)
    max_age = max(
        15.0,
        min(600.0, _f(os.environ.get("NIJA_AUTHORITATIVE_POSITION_SNAPSHOT_MAX_AGE_S"), 90.0)),
    )
    rows = getattr(broker, "_nija_authoritative_position_snapshot_rows_v285", ())
    try:
        row_count = len(tuple(rows or ()))
    except Exception:
        row_count = 0
    return age <= max_age, age, row_count


def _rank(broker: Any) -> tuple[int, int, int, float]:
    current, age, auth_rows = _v285_evidence(broker)
    tracker_rows = _tracker_count(broker)
    return (
        1 if current else 0,
        1 if auth_rows > 0 else 0,
        1 if tracker_rows > 0 else (1 if _connected(broker) else 0),
        -age if current else float("-inf"),
    )


def _reason(new: Any, old: Any) -> str:
    n_current, n_age, n_rows = _v285_evidence(new)
    o_current, o_age, o_rows = _v285_evidence(old)
    if n_current and (not o_current or n_age + 1e-6 < o_age):
        return f"fresher_v285:new_age={n_age:.3f}:old_age={o_age:.3f}"
    if n_rows > o_rows:
        return f"richer_v285_rows:new={n_rows}:old={o_rows}"
    nt = _tracker_count(new)
    ot = _tracker_count(old)
    if nt > ot:
        return f"richer_tracker:new={nt}:old={ot}"
    if _connected(new) and not _connected(old):
        return "connected_over_disconnected"
    return "stronger_canonical_evidence"


def _patch_universal(module: ModuleType) -> bool:
    current = getattr(module, "_register_broker", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    @wraps(current)
    def register_canonical_exit_broker(broker: Any) -> None:
        if broker is None:
            return
        identity = module._logical_identity(broker)
        with module._LOCK:
            existing_match = None
            for existing in module._registered_values():
                if existing is broker:
                    module._start()
                    return
                if module._logical_identity(existing) == identity:
                    existing_match = existing
                    break

            if existing_match is None:
                return current(broker)

            old_rank = _rank(existing_match)
            new_rank = _rank(broker)
            if new_rank <= old_rank:
                module._start()
                return

            reason = _reason(broker, existing_match)
            module._discard_broker(existing_match)
            try:
                module._BROKERS.add(broker)
            except TypeError:
                if broker not in module._STRONG_BROKERS:
                    module._STRONG_BROKERS.append(broker)
            module._DUPLICATE_ACCOUNTS.discard(identity)

        LOGGER.critical(
            "UNIVERSAL_EXIT_BROKER_V331_REBOUND marker=%s venue=%s account=%s "
            "old_class=%s new_class=%s reason=%s old_rank=%s new_rank=%s "
            "broker_state_mutated=false position_state_mutated=false order_submitted=false "
            "readiness_fabricated=false safety_gates_bypassed=false",
            MARKER,
            identity[0],
            identity[1],
            type(existing_match).__name__,
            type(broker).__name__,
            reason,
            old_rank,
            new_rank,
        )
        module._start()

    setattr(register_canonical_exit_broker, _PATCH_ATTR, True)
    setattr(register_canonical_exit_broker, "__wrapped__", current)
    module._register_broker = register_canonical_exit_broker
    return True


def _register_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_universal_exit_broker_rebinding_v331"] = _READY_FLAG
        return True
    except Exception:
        return False


def install_import_hook() -> bool:
    with _LOCK:
        if getattr(builtins, _INSTALL_FLAG, False) and os.environ.get(_READY_FLAG) == "1":
            return True
        try:
            module = importlib.import_module("bot.universal_broker_exit_supervisor_patch")
            patched = _patch_universal(module)
            manifest = _register_manifest()
            ready = bool(patched and manifest)
        except Exception as exc:
            ready = False
            LOGGER.exception(
                "UNIVERSAL_EXIT_BROKER_V331_INSTALL_FAILED marker=%s error=%s:%s "
                "trading_fail_closed=true safety_gates_bypassed=false",
                MARKER, type(exc).__name__, exc,
            )
        os.environ[_READY_FLAG] = "1" if ready else "0"
        setattr(builtins, _INSTALL_FLAG, ready)
        log = LOGGER.critical if ready else LOGGER.error
        log(
            "RUNTIME_UNIVERSAL_EXIT_BROKER_REBINDING_V331_%s marker=%s ready=%s "
            "fresh_v285_preferred=true tracker_evidence_preferred=true connected_preferred=true "
            "equal_evidence_stable=true broker_state_mutated=false position_state_mutated=false "
            "orders_unchanged=true fills_unchanged=true safety_gates_bypassed=false",
            "READY" if ready else "NOT_READY",
            MARKER,
            str(ready).lower(),
        )
        return ready


def install() -> bool:
    return install_import_hook()


__all__ = ["MARKER", "RELEASE_ID", "install", "install_import_hook", "_rank"]
