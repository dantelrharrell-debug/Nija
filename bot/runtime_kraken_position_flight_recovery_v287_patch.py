"""Recover stale Kraken authoritative position single-flights without weakening safety.

v286 intentionally keeps authoritative Kraken Balance reads single-flight and
fail-closed. Production logs on 2026-08-30 showed that a timed-out flight could
remain registered for thousands of seconds, causing every later reconciliation
to reuse the same dead/pending object. A first v287 pass retired flights after a
fixed 75-second ceiling. Follow-up production evidence showed that ceiling was
too close to the legitimate MICRO_CAP monitoring interval (60 seconds), so a
healthy rate-limited worker could be retired while still waiting its turn.

v287 now distinguishes dead workers from live, rate-limited workers. A dead
unfinished worker is retired promptly. A live worker gets a dynamic hard-age
budget of at least three configured Kraken monitoring intervals (90 seconds by
default, 180 seconds for MICRO_CAP). The broker is attached to the flight after
the first bounded caller timeout so later retirement decisions can use its
actual rate profile. Demonstrably stale live workers are still retired, but
ordinary Kraken rate pacing no longer creates avoidable duplicate workers.

The patch never marks a failed read successful, never extends v285 snapshot
freshness, and never fabricates positions, fills, cost basis, balances, or exit
protection. The old worker is not force-cancelled; v286 and the broker's existing
read serialization remain authoritative.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
import time
from functools import wraps
from typing import Any

LOGGER = logging.getLogger("nija.runtime_kraken_position_flight_recovery_v287")
MARKER = "20260830-kraken-position-flight-recovery-v287"
RELEASE_ID = "20260830-runtime-convergence-v287"
_READY_FLAG = "NIJA_RUNTIME_KRAKEN_POSITION_FLIGHT_RECOVERY_V287_READY"
_PATCH_ATTR = "_nija_kraken_position_flight_recovery_v287"
_LOCK = threading.RLock()
_MONITOR_STOP = threading.Event()
_MONITOR_THREAD: threading.Thread | None = None
_MONITOR_RESTARTS = 0


def _float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
        return default if parsed != parsed else parsed
    except Exception:
        return default


def _hard_age_s() -> float:
    """Base stale-flight ceiling before broker-rate-profile expansion."""
    try:
        value = float(os.environ.get("NIJA_KRAKEN_AUTHORITATIVE_POSITION_FLIGHT_MAX_AGE_S", "90") or 90.0)
    except (TypeError, ValueError):
        value = 90.0
    return max(30.0, min(600.0, value))


def _poll_s() -> float:
    try:
        value = float(os.environ.get("NIJA_KRAKEN_POSITION_FLIGHT_RECOVERY_POLL_S", "5") or 5.0)
    except (TypeError, ValueError):
        value = 5.0
    return max(2.0, min(30.0, value))


def _v286() -> Any:
    return importlib.import_module("bot.runtime_kraken_position_refresh_liveness_v286_patch")


def _monitoring_interval_s(broker: Any) -> float:
    """Resolve the configured Kraken monitoring interval for this broker."""
    if broker is None:
        return 0.0
    try:
        module = importlib.import_module("bot.broker_manager")
        calculator = getattr(module, "calculate_min_interval", None)
        enum_cls = getattr(module, "KrakenAPICategory", None)
        mode = getattr(broker, "_kraken_rate_mode", None)
        category = getattr(enum_cls, "MONITORING", None) if enum_cls is not None else None
        if callable(calculator) and category is not None and mode is not None:
            return max(0.0, float(calculator(category, mode) or 0.0))
    except Exception:
        pass
    return max(0.0, _float(getattr(broker, "_min_call_interval", 0.0)))


def _flight_hard_age_s(flight: dict[str, Any]) -> float:
    """Allow at least three legitimate monitoring intervals for live workers."""
    broker = flight.get("broker") if isinstance(flight, dict) else None
    interval = _monitoring_interval_s(broker)
    return min(600.0, max(_hard_age_s(), interval * 3.0 if interval > 0.0 else 0.0))


def _tag_current_flight(broker: Any) -> None:
    """Attach broker identity/rate profile to the currently registered v286 flight."""
    try:
        v286 = _v286()
        auth_lock = getattr(v286, "_AUTH_LOCK", None)
        flights = getattr(v286, "_AUTH_FLIGHTS", None)
    except Exception:
        return
    if auth_lock is None or not isinstance(flights, dict):
        return
    key = id(broker)
    with auth_lock:
        flight = flights.get(key)
        if isinstance(flight, dict):
            flight.setdefault("broker", broker)


def _retire_stale_flights() -> int:
    """Remove only dead or demonstrably over-age unfinished v286 flights."""
    try:
        v286 = _v286()
        auth_lock = getattr(v286, "_AUTH_LOCK", None)
        flights = getattr(v286, "_AUTH_FLIGHTS", None)
    except Exception:
        return 0
    if auth_lock is None or not isinstance(flights, dict):
        return 0

    retired: list[tuple[int, float, float, str]] = []
    now = time.monotonic()
    with auth_lock:
        for key, flight in tuple(flights.items()):
            if not isinstance(flight, dict):
                continue
            event = flight.get("event")
            done = bool(event.is_set()) if callable(getattr(event, "is_set", None)) else False
            if done:
                continue
            age = max(0.0, now - _float(flight.get("started_at")))
            thread = flight.get("thread")
            thread_alive = bool(thread.is_alive()) if callable(getattr(thread, "is_alive", None)) else True
            hard_age = _flight_hard_age_s(flight)
            reason = "dead_worker" if not thread_alive and age >= 2.0 else "over_hard_age" if age >= hard_age else ""
            if not reason:
                continue
            if flights.get(key) is flight:
                flights.pop(key, None)
                retired.append((int(key), age, hard_age, reason))

    for key, age, hard_age, reason in retired:
        LOGGER.warning(
            "KRAKEN_POSITION_V287_STALE_FLIGHT_RETIRED marker=%s broker_id=%s age_s=%.1f hard_age_s=%.1f reason=%s old_worker_cancelled=false synthetic_success=false snapshot_freshness_unchanged=true safety_gates_bypassed=false",
            MARKER,
            key,
            age,
            hard_age,
            reason,
        )
    return len(retired)


def _patch_authoritative_positions() -> bool:
    try:
        v286 = _v286()
    except Exception:
        return False
    current = getattr(v286, "_authoritative_positions", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True
    original = current

    @wraps(original)
    def authoritative_positions_v287(broker: Any):
        _retire_stale_flights()
        try:
            return original(broker)
        finally:
            # v286 deliberately returns a bounded timeout while its worker may
            # continue. Tag that retained flight so the monitor can distinguish
            # legitimate MICRO_CAP pacing from a genuinely stale worker.
            _tag_current_flight(broker)

    setattr(authoritative_positions_v287, _PATCH_ATTR, True)
    setattr(authoritative_positions_v287, "__wrapped__", original)
    v286._authoritative_positions = authoritative_positions_v287
    return True


def _register_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_kraken_position_flight_recovery_v287"] = _READY_FLAG
        return True
    except Exception:
        return False


def reconcile_once() -> dict[str, Any]:
    patched = _patch_authoritative_positions()
    retired = _retire_stale_flights()
    downstream: dict[str, Any] = {}
    try:
        v286 = _v286()
        reconcile = getattr(v286, "reconcile_once", None)
        result = reconcile() if callable(reconcile) else {}
        downstream = dict(result) if isinstance(result, dict) else {}
    except Exception as exc:
        downstream = {"ready": False, "pending": {"__v287__": (f"v286_reconcile_error:{type(exc).__name__}:{exc}",)}}
    return {
        "ready": bool(patched and downstream.get("ready")),
        "retired_stale_flights": retired,
        "downstream": downstream,
    }


def _monitor() -> None:
    while not _MONITOR_STOP.wait(_poll_s()):
        try:
            _patch_authoritative_positions()
            _retire_stale_flights()
        except BaseException as exc:
            LOGGER.error(
                "KRAKEN_POSITION_V287_MONITOR_ERROR marker=%s error=%s:%s fail_closed=true",
                MARKER,
                type(exc).__name__,
                exc,
            )


def _ensure_monitor() -> bool:
    global _MONITOR_THREAD, _MONITOR_RESTARTS
    with _LOCK:
        if _MONITOR_THREAD is not None and _MONITOR_THREAD.is_alive():
            return True
        if _MONITOR_STOP.is_set():
            _MONITOR_STOP.clear()
        _MONITOR_RESTARTS += 1
        _MONITOR_THREAD = threading.Thread(
            target=_monitor,
            name="KrakenPositionFlightRecoveryV287",
            daemon=True,
        )
        _MONITOR_THREAD.start()
        return True


def install() -> bool:
    manifest_ok = _register_manifest()
    patched = _patch_authoritative_positions()
    monitor_ok = _ensure_monitor()
    retired = _retire_stale_flights()
    ready = bool(manifest_ok and patched and monitor_ok)
    os.environ[_READY_FLAG] = "1" if ready else "0"
    LOGGER.critical(
        "RUNTIME_KRAKEN_POSITION_FLIGHT_RECOVERY_V287_%s marker=%s ready=%s retired_on_install=%d base_hard_age_s=%.1f dynamic_rate_budget=true dead_worker_fast_retirement=true stale_flight_reuse_blocked=true old_worker_cancelled=false authoritative_fetch_still_required=true snapshot_freshness_unchanged=true position_success_fabricated=false forced_trade=false forced_activation=false writer_nonce_risk_capital_killswitch_order_fill_gates_unchanged=true safety_gates_bypassed=false",
        "READY" if ready else "NOT_READY",
        MARKER,
        str(ready).lower(),
        retired,
        _hard_age_s(),
    )
    return ready


def install_import_hook() -> bool:
    return install()


def stop() -> None:
    _MONITOR_STOP.set()


__all__ = [
    "MARKER", "RELEASE_ID", "install", "install_import_hook", "stop",
    "reconcile_once", "_hard_age_s", "_monitoring_interval_s",
    "_flight_hard_age_s", "_tag_current_flight", "_retire_stale_flights",
    "_patch_authoritative_positions",
]
