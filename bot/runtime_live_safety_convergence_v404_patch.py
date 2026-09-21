"""Fail-closed convergence for live safety telemetry and Kraken snapshot freshness.

This patch does not grant execution authority, change protection thresholds,
relax authoritative snapshot freshness, submit/cancel orders, or bypass any
writer/nonce/capital/risk/kill-switch/protective-exit gate.

It only:
* makes OHLC cycle telemetry report new_entry_allowed=False whenever the
  canonical market-data health verdict is false;
* suppresses the stalled-writer WAITING warning when the writer is already
  LIVE_ACTIVE with execution authority, manager readiness, and capital readiness;
* tightens the read-only V390 user-position refresh cadence while keeping the
  existing 90-second authoritative snapshot TTL unchanged;
* immediately re-arms an account for the next normal V390 refresh attempt when
  a completed authenticated refresh still leaves its snapshot stale.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
from functools import wraps
from typing import Any

LOGGER = logging.getLogger("nija.runtime_live_safety_convergence_v404")
MARKER = "20260908-runtime-live-safety-convergence-v404"
_LOCK = threading.RLock()
_INSTALLED = False
_USER_REFRESH_MONITOR_STARTED = False
_USER_REFRESH_MONITOR_STOP = threading.Event()
USER_REFRESH_LIVENESS_MARKER = "20260921-user-position-refresh-liveness-v422"

_TELEMETRY_ATTR = "_nija_live_safety_v404_telemetry"
_V390_INTERVAL_ATTR = "_nija_live_safety_v404_v390_interval"
_V390_RUN_ATTR = "_nija_live_safety_v404_v390_run"
_FILTER_ATTR = "_nija_live_safety_v404_filter"


def _patch_market_data_telemetry() -> bool:
    module = importlib.import_module("bot.ohlc_worker_pool")
    cls = getattr(module, "OHLCWorkerPool", None)
    if not isinstance(cls, type):
        return False
    current = getattr(cls, "emit_cycle_telemetry", None)
    if not callable(current):
        return False
    if getattr(current, _TELEMETRY_ATTR, False):
        return True

    original = current

    @wraps(original)
    def emit_cycle_telemetry_v404(
        self: Any,
        runtime_state: str,
        execution_authority: int,
        scan_symbols: int,
        new_entry_allowed: bool,
    ) -> None:
        try:
            healthy, _detail = self.compute_market_data_healthy(
                runtime_state=runtime_state,
                execution_authority=execution_authority,
            )
        except Exception:
            healthy = False
        effective_allowed = bool(new_entry_allowed and healthy)
        if bool(new_entry_allowed) and not effective_allowed:
            LOGGER.warning(
                "MARKET_DATA_ENTRY_TELEMETRY_V404_FAILCLOSED marker=%s "
                "caller_allowed=true effective_allowed=false market_data_healthy=false "
                "orders_submitted=false execution_gate_unchanged=true",
                MARKER,
            )
        return original(
            self,
            runtime_state,
            execution_authority,
            scan_symbols,
            effective_allowed,
        )

    setattr(emit_cycle_telemetry_v404, _TELEMETRY_ATTR, True)
    setattr(emit_cycle_telemetry_v404, "__wrapped__", original)
    cls.emit_cycle_telemetry = emit_cycle_telemetry_v404
    return True


class _HealthyWriterWaitingFilter(logging.Filter):
    """Hide only the known false-positive V22 WAITING warning."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            return True
        if "STALLED_WRITER_RELEASE_GUARD_V22_WAITING" not in message:
            return True
        healthy_active = all(
            token in message
            for token in (
                "state=LIVE_ACTIVE",
                "authority=True",
                "manager_ready=True",
                "capital_ready=True",
            )
        )
        return not healthy_active


def _patch_stalled_writer_warning() -> bool:
    target = logging.getLogger("nija.stalled_writer_release_guard_v22")
    for filt in list(target.filters):
        if getattr(filt, _FILTER_ATTR, False):
            return True
    filt = _HealthyWriterWaitingFilter()
    setattr(filt, _FILTER_ATTR, True)
    target.addFilter(filt)
    return True


def _patch_v390_user_refresh() -> bool:
    v285 = importlib.import_module("bot.runtime_authoritative_position_coverage_v285_patch")
    safe_interval = getattr(v285, "_user_refresh_safe_interval_v390", None)
    run_refresh = getattr(v285, "_run_user_refresh_v390", None)
    snapshot_status = getattr(v285, "_snapshot_status", None)
    due_map = getattr(v285, "_USER_NEXT_REFRESH", None)
    if not callable(safe_interval) or not callable(run_refresh) or not callable(snapshot_status):
        return False
    if not isinstance(due_map, dict):
        return False

    if not getattr(safe_interval, _V390_INTERVAL_ATTR, False):
        original_interval = safe_interval

        @wraps(original_interval)
        def safe_interval_v404(user_count: int) -> float:
            original = float(original_interval(user_count))
            try:
                ttl = float(getattr(v285, "_snapshot_max_age_s")())
            except Exception:
                ttl = 90.0
            # Keep at least 2/3 of the TTL as refresh headroom. With the current
            # 90s TTL this caps a healthy two-user cadence at 20s rather than 30s.
            headroom_cap = max(10.0, ttl / 4.5)
            return max(10.0, min(original, headroom_cap))

        setattr(safe_interval_v404, _V390_INTERVAL_ATTR, True)
        setattr(safe_interval_v404, "__wrapped__", original_interval)
        setattr(v285, "_user_refresh_safe_interval_v390", safe_interval_v404)

    current_run = getattr(v285, "_run_user_refresh_v390", None)
    if callable(current_run) and not getattr(current_run, _V390_RUN_ATTR, False):
        original_run = current_run

        @wraps(original_run)
        def run_refresh_v404(
            manager: Any,
            account: str,
            broker: Any,
            prior_reason: str,
            prior_snapshot_reason: str,
            connected_users: int,
            safe_interval_value: float,
            ttl: float,
            flight_token: int | None = None,
        ) -> None:
            if flight_token is None:
                original_run(
                    manager,
                    account,
                    broker,
                    prior_reason,
                    prior_snapshot_reason,
                    connected_users,
                    safe_interval_value,
                    ttl,
                )
            else:
                original_run(
                    manager,
                    account,
                    broker,
                    prior_reason,
                    prior_snapshot_reason,
                    connected_users,
                    safe_interval_value,
                    ttl,
                    flight_token,
                )
            try:
                ok, reason, _rows, age_s, _generation = snapshot_status(broker)
            except Exception as exc:
                LOGGER.warning(
                    "AUTHORITATIVE_USER_POSITION_V404_POST_REFRESH_CHECK_FAILED "
                    "marker=%s account=%s error=%s:%s fail_closed=true",
                    MARKER,
                    account,
                    type(exc).__name__,
                    exc,
                )
                return
            if ok:
                return
            reason_text = str(reason or "")
            if not reason_text.startswith("stale_position_snapshot"):
                return
            # Re-arm only the scheduling timestamp. The next attempt still goes
            # through V390's existing authenticated adopter, rate/nonce controls,
            # same-account single-flight, and all readiness/protection proofs.
            due_map[str(account)] = 0.0
            LOGGER.warning(
                "AUTHORITATIVE_USER_POSITION_V404_IMMEDIATE_REARM marker=%s "
                "account=%s age_s=%s reason=%s snapshot_ttl_unchanged=true "
                "readiness_granted=false eligibility_granted=false orders_submitted=false "
                "exits_preserved=true safety_gates_bypassed=false",
                MARKER,
                account,
                age_s,
                reason_text,
            )

        setattr(run_refresh_v404, _V390_RUN_ATTR, True)
        setattr(run_refresh_v404, "__wrapped__", original_run)
        setattr(v285, "_run_user_refresh_v390", run_refresh_v404)

    return True


def _user_refresh_poll_s_v422() -> float:
    try:
        value = float(os.environ.get("NIJA_USER_POSITION_REFRESH_LIVENESS_POLL_S", "5") or 5.0)
    except (TypeError, ValueError):
        value = 5.0
    return max(2.0, min(30.0, value))


def _user_refresh_liveness_tick_v422() -> str:
    """Dispatch only the existing bounded v390 user refresh path."""
    try:
        v86 = importlib.import_module("bot.kraken_all_account_supervision_v86")
        writer_proof = getattr(v86, "_writer_proof", None)
        if not callable(writer_proof):
            return "writer_proof_unavailable"
        writer_ok, writer_reason = writer_proof()
        if not writer_ok:
            return f"writer_unready:{writer_reason}"

        v285 = importlib.import_module("bot.runtime_authoritative_position_coverage_v285_patch")
        manager_getter = getattr(v285, "_canonical_manager", None)
        refresh = getattr(v285, "_refresh_one_user_v390", None)
        if not callable(manager_getter) or not callable(refresh):
            return "v390_refresh_unavailable"
        manager = manager_getter()
        if manager is None:
            return "manager_unavailable"
        result = str(refresh(manager) or "no_user_refresh_needed")
        return result
    except Exception as exc:
        LOGGER.warning(
            "AUTHORITATIVE_USER_POSITION_V422_TICK_FAILED marker=%s error=%s:%s "
            "readiness_granted=false execution_authority_unchanged=true safety_gates_bypassed=false",
            USER_REFRESH_LIVENESS_MARKER,
            type(exc).__name__,
            exc,
        )
        return f"tick_error:{type(exc).__name__}"


def _user_refresh_liveness_monitor_v422() -> None:
    interval = _user_refresh_poll_s_v422()
    last_result = ""
    while not _USER_REFRESH_MONITOR_STOP.wait(interval):
        result = _user_refresh_liveness_tick_v422()
        if result == last_result:
            continue
        last_result = result
        if "refresh_dispatched" in result or result.endswith(":ready"):
            LOGGER.info(
                "AUTHORITATIVE_USER_POSITION_V422_LIVENESS marker=%s result=%s "
                "writer_proof_required=true existing_v390_path_only=true per_account_single_flight_preserved=true "
                "snapshot_ttl_unchanged=true kraken_rate_limits_unchanged=true nonce_ordering_unchanged=true "
                "readiness_granted=false eligibility_fabricated=false orders_submitted=false safety_gates_bypassed=false",
                USER_REFRESH_LIVENESS_MARKER,
                result,
            )


def _start_user_refresh_liveness_monitor_v422() -> bool:
    global _USER_REFRESH_MONITOR_STARTED
    if _USER_REFRESH_MONITOR_STARTED:
        return True
    _USER_REFRESH_MONITOR_STARTED = True
    threading.Thread(
        target=_user_refresh_liveness_monitor_v422,
        name="AuthoritativeUserRefreshLivenessV422",
        daemon=True,
    ).start()
    LOGGER.critical(
        "AUTHORITATIVE_USER_POSITION_V422_MONITOR_READY marker=%s poll_s=%.1f "
        "writer_proof_required=true existing_v390_path_only=true snapshot_ttl_unchanged=true "
        "readiness_granted=false orders_submitted=false safety_gates_bypassed=false",
        USER_REFRESH_LIVENESS_MARKER,
        _user_refresh_poll_s_v422(),
    )
    return True

def install() -> bool:
    global _INSTALLED
    with _LOCK:
        if _INSTALLED:
            return True
        telemetry_ok = _patch_market_data_telemetry()
        writer_warning_ok = _patch_stalled_writer_warning()
        refresh_ok = _patch_v390_user_refresh()
        refresh_monitor_ok = _start_user_refresh_liveness_monitor_v422() if refresh_ok else False
        ready = bool(telemetry_ok and writer_warning_ok and refresh_ok and refresh_monitor_ok)
        os.environ["NIJA_RUNTIME_LIVE_SAFETY_CONVERGENCE_V404_READY"] = "1" if ready else "0"
        LOGGER.critical(
            "RUNTIME_LIVE_SAFETY_CONVERGENCE_V404 marker=%s ready=%s "
            "market_data_telemetry_failclosed=%s healthy_writer_false_warning_suppressed=%s "
            "kraken_user_refresh_tightened=%s snapshot_ttl_unchanged=true "
            "protection_thresholds_unchanged=true execution_authority_unchanged=true "
            "orders_submitted=false orders_cancelled=false safety_gates_bypassed=false",
            MARKER,
            str(ready).lower(),
            str(telemetry_ok).lower(),
            str(writer_warning_ok).lower(),
            str(refresh_ok).lower(), str(refresh_monitor_ok).lower(),
        )
        _INSTALLED = ready
        return ready


__all__ = ["install", "MARKER", "USER_REFRESH_LIVENESS_MARKER", "_user_refresh_liveness_tick_v422"]