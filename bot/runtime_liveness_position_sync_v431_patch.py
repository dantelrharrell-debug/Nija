"""Prevent capital refresh generation buildup and decouple stale platform position recovery.

Production after v164/v355 proved two remaining liveness defects:

* v164 caps the number of live retired capital-refresh generations, but it can
  still permit multiple timed-out daemon generations before the cap is reached.
  Python cannot safely kill an arbitrary thread blocked in broker/library code,
  so the safe repair is to preserve single-flight ownership: while the current
  timed-out generation is still alive, coordinator rollover is deferred. A new
  generation may start only after the old worker has genuinely unwound.
* v355 makes stale authoritative platform snapshots discoverable by v108, but
  v108 dispatch is normally driven by refresh_capital_authority(). If capital
  refresh itself is unhealthy, position recovery can therefore remain coupled
  to the failing subsystem. A small recovery pulse now invokes the existing
  v108 dispatcher independently; v355/v285 still decide whether any broker is
  actually eligible for refresh, and v108 keeps its existing single-flight,
  authenticated fetch, retry, and adoption semantics.

No thread is force-killed. No freshness TTL is extended. No stale snapshot is
promoted. No position, capital, order, fill, execution proof, SL/TP proof, or
protective coverage is fabricated. Writer, nonce, risk, kill-switch, ECEL,
minimum-notional, acknowledgement, fill, and protection gates are unchanged.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
import time
from functools import wraps
from typing import Any

LOGGER = logging.getLogger("nija.runtime_liveness_position_sync_v431")
MARKER = "20260925-runtime-liveness-position-sync-v431"
RELEASE_ID = "20260925-runtime-convergence-v431"
_READY_FLAG = "NIJA_RUNTIME_LIVENESS_POSITION_SYNC_V431_READY"
_PATCH_ATTR = "_nija_runtime_liveness_position_sync_v431"
_LOCK = threading.RLock()
_MONITOR_STARTED = False


def _canonical_manager() -> Any:
    try:
        module = importlib.import_module("bot.multi_account_broker_manager")
        getter = getattr(module, "get_broker_manager", None)
        if callable(getter):
            return getter()
        return getattr(module, "_manager", None) or getattr(
            module, "multi_account_broker_manager", None
        )
    except Exception:
        return None


def _thread_alive(coordinator: Any) -> bool:
    thread = getattr(coordinator, "_nija_v142_flight_thread", None)
    alive = getattr(thread, "is_alive", None) if thread is not None else None
    return bool(alive()) if callable(alive) else False


def _patch_capital_single_generation() -> bool:
    """Never overlap runtime refresh generations.

    Timed-out threads remain generation-fenced by v142. This wrapper only
    prevents creating another coordinator while that exact worker is still
    alive. Once it actually exits, the existing v142/v164 rollover path may
    proceed normally.
    """
    try:
        v142 = importlib.import_module("bot.capital_publication_liveness_v142_patch")
    except Exception:
        return False
    current = getattr(v142, "_rollover_coordinator", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True
    original = current

    @wraps(original)
    def rollover_v431(
        manager: Any,
        *,
        expected_old: Any = None,
        reason: str,
    ) -> Any:
        old = getattr(manager, "_capital_coordinator", None)
        if old is not None and (expected_old is None or old is expected_old):
            if _thread_alive(old):
                LOGGER.critical(
                    "CAPITAL_V431_ROLLOVER_DEFERRED marker=%s reason=%s "
                    "old_worker_alive=true new_generation_started=false "
                    "single_runtime_generation=true generation_fence_preserved=true "
                    "trading_fail_closed_until_unwind=true",
                    MARKER,
                    reason,
                )
                return old
        return original(manager, expected_old=expected_old, reason=reason)

    setattr(rollover_v431, _PATCH_ATTR, True)
    setattr(rollover_v431, "__wrapped__", original)
    v142._rollover_coordinator = rollover_v431
    return True


def _position_recovery_interval_s() -> float:
    raw = str(os.environ.get("NIJA_POSITION_RECOVERY_PULSE_S", "2.0") or "2.0").strip()
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = 2.0
    return max(0.5, min(value, 10.0))


def _position_recovery_pulse() -> int:
    """Run existing v108/v355/v285 recovery discovery independent of capital."""
    manager = _canonical_manager()
    if manager is None:
        return 0
    try:
        v108 = importlib.import_module("bot.platform_position_sync_v108_patch")
        dispatch = getattr(v108, "dispatch_platform_position_sync", None)
        if not callable(dispatch):
            return 0
        return int(dispatch(manager, trigger="runtime_liveness_v431") or 0)
    except Exception as exc:
        LOGGER.warning(
            "POSITION_V431_RECOVERY_PULSE_DEFERRED marker=%s error=%s:%s "
            "readiness_unchanged=true fail_closed=true",
            MARKER,
            type(exc).__name__,
            exc,
        )
        return 0


def _monitor() -> None:
    interval = _position_recovery_interval_s()
    while True:
        try:
            started = _position_recovery_pulse()
            if started:
                LOGGER.info(
                    "POSITION_V431_RECOVERY_DISPATCH marker=%s workers_started=%d "
                    "capital_refresh_required=false authoritative_fetch_required=true "
                    "snapshot_ttl_unchanged=true stale_promoted=false",
                    MARKER,
                    started,
                )
        except BaseException as exc:
            LOGGER.warning(
                "POSITION_V431_MONITOR_ERROR marker=%s error=%s:%s fail_closed=true",
                MARKER,
                type(exc).__name__,
                exc,
            )
        time.sleep(interval)


def _start_monitor() -> bool:
    global _MONITOR_STARTED
    if _MONITOR_STARTED:
        return True
    try:
        thread = threading.Thread(
            target=_monitor,
            name="runtime-liveness-position-sync-v431-monitor",
            daemon=True,
        )
        thread.start()
        _MONITOR_STARTED = True
        return True
    except Exception:
        return False


def _register_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_liveness_position_sync_v431"] = _READY_FLAG
        return True
    except Exception:
        return False


def install() -> bool:
    with _LOCK:
        capital_ok = _patch_capital_single_generation()
        monitor_ok = _start_monitor()
        manifest_ok = _register_manifest()
        ready = bool(capital_ok and monitor_ok and manifest_ok)
        os.environ[_READY_FLAG] = "1" if ready else "0"
        if ready:
            LOGGER.critical(
                "RUNTIME_LIVENESS_POSITION_SYNC_V431_READY marker=%s ready=true "
                "capital_single_runtime_generation=true force_thread_kill=false "
                "position_recovery_capital_independent=true v108_single_flight_preserved=true "
                "v285_authoritative_truth_preserved=true snapshot_ttl_unchanged=true "
                "writer_gate_unchanged=true nonce_gate_unchanged=true risk_gate_unchanged=true "
                "kill_switch_unchanged=true ecel_unchanged=true minimum_notional_unchanged=true "
                "ack_fill_sl_tp_protection_gates_unchanged=true forced_trade=false "
                "execution_proof_fabricated=false safety_gates_bypassed=false",
                MARKER,
            )
        else:
            LOGGER.critical(
                "RUNTIME_LIVENESS_POSITION_SYNC_V431_FAILED marker=%s capital_ok=%s "
                "monitor_ok=%s manifest_ok=%s trading_fail_closed=true",
                MARKER,
                str(capital_ok).lower(),
                str(monitor_ok).lower(),
                str(manifest_ok).lower(),
            )
        return ready


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "RELEASE_ID",
    "install",
    "install_import_hook",
    "_thread_alive",
    "_patch_capital_single_generation",
    "_position_recovery_interval_s",
    "_position_recovery_pulse",
    "_start_monitor",
]
