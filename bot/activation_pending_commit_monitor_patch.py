"""Prompt live activation commits when all normal gates are ready.

The monitor remains fail-closed: it only re-invokes the existing activation commit
after CapitalAuthority has accepted a real live snapshot.  Startup repair modules
are deliberately deferred until the canonical broker manager has loaded so Python
site startup can never hold the production entrypoint before broker construction.
"""

from __future__ import annotations

import builtins
import importlib
import logging
import os
import sys
import threading
import time
from typing import Any

logger = logging.getLogger("nija.activation_pending_commit_monitor")
_TRUTHY = {"1", "true", "yes", "on", "enabled", "y"}
_MARKER = "20260711c"
_STARTUP_REPAIR_MODULES: tuple[tuple[str, str, str], ...] = (
    ("final_stage_venue_routing_repair_patch", "FINAL_STAGE_VENUE_ROUTING_REPAIR_INSTALL_REQUESTED", "20260709n"),
    ("final_stage_venue_resolution_cache_patch", "FINAL_STAGE_BROKER_RESOLUTION_CACHE_INSTALL_REQUESTED", "20260709r"),
    ("closed_candle_volume_repair_patch", "CLOSED_CANDLE_VOLUME_REPAIR_INSTALL_REQUESTED", "20260709q"),
    ("platform_tier_live_capital_patch", "PLATFORM_TIER_LIVE_CAPITAL_INSTALL_REQUESTED", "20260709s"),
    ("hard_controls_capital_authority_bridge_patch", "HARD_CONTROLS_CA_BRIDGE_INSTALL_REQUESTED", "20260709t"),
    ("runtime_authority_convergence_repair_patch", "RUNTIME_AUTHORITY_CONVERGENCE_INSTALL_REQUESTED", "20260709u"),
    ("writer_authority_recursion_guard_patch", "WRITER_AUTHORITY_RECURSION_GUARD_INSTALL_REQUESTED", "20260709aq"),
    ("operator_emergency_stop_preexec_clear_patch", "OPERATOR_EMERGENCY_STOP_PREEXEC_CLEAR_INSTALL_REQUESTED", "20260709ai"),
    ("execution_nonce_authority_snapshot_repair_patch", "EXECUTION_NONCE_AUTHORITY_SNAPSHOT_REPAIR_INSTALL_REQUESTED", "20260709aj"),
    ("startup_coordinator_live_capital_state_repair_patch", "STARTUP_COORDINATOR_LIVE_CAPITAL_REPAIR_INSTALL_REQUESTED", "20260709ak"),
    ("phase3_scan_stall_guard_patch", "PHASE3_SCAN_STALL_GUARD_INSTALL_REQUESTED", "20260709an"),
    ("broker_native_quote_routing_patch", "BROKER_NATIVE_QUOTE_ROUTING_INSTALL_REQUESTED", "20260709y"),
    ("execution_route_metadata_consistency_patch", "EXECUTION_ROUTE_METADATA_CONSISTENCY_INSTALL_REQUESTED", "20260709ar"),
    ("ecel_invalid_order_fail_closed_patch", "ECEL_INVALID_ORDER_FAIL_CLOSED_INSTALL_REQUESTED", "20260709as"),
    ("execution_minimum_position_micro_broker_repair_patch", "EXECUTION_MICRO_BROKER_MINIMUM_REPAIR_INSTALL_REQUESTED", "20260709aa"),
    ("execution_ack_timeout_failover_patch", "EXECUTION_ACK_TIMEOUT_FAILOVER_INSTALL_REQUESTED", "20260709ab"),
    ("execution_entry_timeout_guard_patch", "EXECUTION_ENTRY_TIMEOUT_GUARD_INSTALL_REQUESTED", "20260709ae"),
    ("kraken_tier_floor_platform_capital_repair_patch", "KRAKEN_TIER_FLOOR_PLATFORM_CAPITAL_REPAIR_INSTALL_REQUESTED", "20260709ad"),
    ("execution_soft_reject_classification_patch", "EXECUTION_SOFT_REJECT_CLASSIFICATION_INSTALL_REQUESTED", "20260709af"),
    ("execution_minimum_position_boundary_tolerance_patch", "EXECUTION_MIN_POSITION_BOUNDARY_TOLERANCE_INSTALL_REQUESTED", "20260709ag"),
)


def _process_object(name: str, factory):
    value = getattr(builtins, name, None)
    if value is None:
        value = factory()
        setattr(builtins, name, value)
    return value


_PROCESS_LOCK: threading.RLock = _process_object(
    "_NIJA_ACTIVATION_PENDING_PROCESS_LOCK_20260711c", threading.RLock
)
_STARTUP_REPAIRS_READY: threading.Event = _process_object(
    "_NIJA_STARTUP_EXECUTION_REPAIRS_READY_EVENT_20260711c", threading.Event
)
_STARTUP_REPAIRS_INSTALLED: set[str] = _process_object(
    "_NIJA_STARTUP_EXECUTION_REPAIRS_INSTALLED_20260711c", set
)


class _VenueBindDuplicateFilter(logging.Filter):
    """Suppress identical OKX late-bind lines while preserving state changes."""

    def __init__(self) -> None:
        super().__init__()
        self._last_message = ""
        self._last_at = 0.0
        self._lock = threading.Lock()

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:
            return True
        if not message.startswith("OKX_LATE_BIND_COMPLETE"):
            return True
        now = time.monotonic()
        with self._lock:
            if message == self._last_message and now - self._last_at < 30.0:
                return False
            self._last_message = message
            self._last_at = now
        return True


def _install_venue_bind_log_filter() -> None:
    guard_name = "_NIJA_VENUE_BIND_LOG_FILTER_20260711c"
    with _PROCESS_LOCK:
        if getattr(builtins, guard_name, None) is not None:
            return
        log_filter = _VenueBindDuplicateFilter()
        logging.getLogger("nija.venue_readiness_execution_repair").addFilter(log_filter)
        setattr(builtins, guard_name, log_filter)


def _truthy(name: str, default: str = "false") -> bool:
    return str(os.environ.get(name, default)).strip().lower() in _TRUTHY


def _live_mode() -> bool:
    return (
        _truthy("LIVE_CAPITAL_VERIFIED")
        and not _truthy("DRY_RUN_MODE")
        and not _truthy("PAPER_MODE")
    )


def _loaded_module(*names: str) -> Any:
    """Observe already-loaded modules without pulling runtime ahead of bootstrap."""

    for name in names:
        module = sys.modules.get(name)
        if module is not None:
            return module
    return None


def _import_repair_module(*names: str) -> Any:
    for name in names:
        try:
            return importlib.import_module(name)
        except Exception:
            continue
    return None


def _broker_manager_module_loaded() -> bool:
    return _loaded_module(
        "bot.multi_account_broker_manager", "multi_account_broker_manager"
    ) is not None


def _install_startup_execution_repairs() -> bool:
    """Install each repair once, only after normal broker bootstrap has begun."""

    with _PROCESS_LOCK:
        missing: list[str] = []
        for mod_name, log_marker, marker in _STARTUP_REPAIR_MODULES:
            if mod_name in _STARTUP_REPAIRS_INSTALLED:
                continue
            try:
                mod = _import_repair_module(f"bot.{mod_name}", mod_name)
                installer = (
                    getattr(mod, "install_import_hook", None)
                    if mod is not None
                    else None
                )
                if not callable(installer):
                    missing.append(mod_name)
                    continue
                installer()
                _STARTUP_REPAIRS_INSTALLED.add(mod_name)
                logger.warning(
                    "%s marker=%s source=activation_pending_deferred",
                    log_marker,
                    marker,
                )
            except Exception as exc:
                missing.append(mod_name)
                logger.warning(
                    "%s_FAILED marker=%s source=activation_pending_deferred err=%s",
                    log_marker,
                    marker,
                    exc,
                )

        complete = len(_STARTUP_REPAIRS_INSTALLED) == len(_STARTUP_REPAIR_MODULES)
        if complete:
            os.environ["NIJA_STARTUP_EXECUTION_REPAIRS_READY"] = "1"
            os.environ.pop("NIJA_STARTUP_EXECUTION_REPAIRS_FAILED", None)
            _STARTUP_REPAIRS_READY.set()
            logger.warning(
                "STARTUP_EXECUTION_REPAIRS_READY marker=%s installed=%d",
                _MARKER,
                len(_STARTUP_REPAIRS_INSTALLED),
            )
        else:
            os.environ["NIJA_STARTUP_EXECUTION_REPAIRS_READY"] = "0"
            logger.warning(
                "STARTUP_EXECUTION_REPAIRS_INCOMPLETE marker=%s installed=%d/%d missing=%s",
                _MARKER,
                len(_STARTUP_REPAIRS_INSTALLED),
                len(_STARTUP_REPAIR_MODULES),
                ",".join(missing),
            )
        return complete


def _startup_repairs_worker() -> None:
    interval = max(
        0.5,
        float(os.environ.get("NIJA_STARTUP_REPAIRS_RETRY_S", "2") or 2.0),
    )
    timeout_s = max(
        30.0,
        float(os.environ.get("NIJA_STARTUP_REPAIRS_TIMEOUT_S", "300") or 300.0),
    )
    deadline = time.monotonic() + timeout_s
    last_wait_log = 0.0
    logger.warning(
        "STARTUP_EXECUTION_REPAIRS_DEFERRED marker=%s wait_for=broker_manager_module",
        _MARKER,
    )

    while time.monotonic() < deadline:
        if not _live_mode():
            os.environ["NIJA_STARTUP_EXECUTION_REPAIRS_READY"] = "1"
            _STARTUP_REPAIRS_READY.set()
            return

        if not _broker_manager_module_loaded():
            now = time.monotonic()
            if now - last_wait_log >= 15.0:
                logger.warning(
                    "STARTUP_EXECUTION_REPAIRS_WAITING marker=%s reason=broker_manager_module_not_loaded",
                    _MARKER,
                )
                last_wait_log = now
            time.sleep(interval)
            continue

        if _install_startup_execution_repairs():
            return
        time.sleep(interval)

    os.environ["NIJA_STARTUP_EXECUTION_REPAIRS_FAILED"] = "1"
    logger.error(
        "STARTUP_EXECUTION_REPAIRS_TIMEOUT marker=%s timeout_s=%.1f "
        "installed=%d/%d trading_gates_remain_fail_closed=true",
        _MARKER,
        timeout_s,
        len(_STARTUP_REPAIRS_INSTALLED),
        len(_STARTUP_REPAIR_MODULES),
    )


def ensure_startup_execution_repairs_ready(timeout_s: float | None = None) -> bool:
    """Allow later startup stages to prove the deferred repair set is complete."""

    install_import_hook()
    if _STARTUP_REPAIRS_READY.is_set():
        return True

    if _broker_manager_module_loaded():
        _install_startup_execution_repairs()
    if _STARTUP_REPAIRS_READY.is_set():
        return True

    if timeout_s is None:
        timeout_s = max(
            1.0,
            float(
                os.environ.get(
                    "NIJA_STARTUP_REPAIRS_CALLER_WAIT_S", "90"
                )
                or 90.0
            ),
        )
    return _STARTUP_REPAIRS_READY.wait(max(0.0, float(timeout_s)))


def _install_final_stage_venue_routing_repair() -> None:
    """Backward-compatible installer entrypoint."""

    if _broker_manager_module_loaded():
        _install_startup_execution_repairs()


def _state_machine() -> Any:
    module = _loaded_module("bot.trading_state_machine", "trading_state_machine")
    if module is None:
        return None
    getter = getattr(module, "get_state_machine", None)
    if callable(getter):
        try:
            return getter()
        except Exception as exc:
            logger.debug("get_state_machine failed: %s", exc)
    return None


def _capital_ready_snapshot() -> tuple[bool, dict[str, Any]]:
    module = _loaded_module("bot.capital_authority", "capital_authority")
    if module is None:
        return False, {"reason": "capital_authority_unavailable"}
    getter = getattr(module, "get_capital_authority", None)
    if not callable(getter):
        return False, {"reason": "capital_authority_getter_unavailable"}
    try:
        ca = getter()
    except Exception as exc:
        return False, {"reason": f"capital_authority_error:{exc}"}
    if ca is None:
        return False, {"reason": "capital_authority_none"}

    hydrated = bool(getattr(ca, "is_hydrated", False))
    real = 0.0
    try:
        reader = getattr(ca, "get_real_capital", None)
        real = float(
            reader()
            if callable(reader)
            else getattr(ca, "total_capital", 0.0)
            or 0.0
        )
    except Exception:
        try:
            real = float(getattr(ca, "total_capital", 0.0) or 0.0)
        except Exception:
            real = 0.0

    stale = True
    try:
        is_stale = getattr(ca, "is_stale", None)
        stale = bool(
            is_stale() if callable(is_stale) else getattr(ca, "stale", True)
        )
    except Exception:
        stale = True

    accepted_latch = bool(
        getattr(ca, "first_snap_accepted", False)
        or getattr(ca, "_first_snap_accepted", False)
        or getattr(ca, "first_snapshot_accepted", False)
    )
    try:
        registered = int(getattr(ca, "registered_broker_count", 0) or 0)
    except Exception:
        registered = 0

    accepted = bool(
        accepted_latch
        or (hydrated and real > 0.0 and registered > 0 and not stale)
    )
    return accepted, {
        "hydrated": hydrated,
        "real_capital": real,
        "stale": stale,
        "registered_brokers": registered,
        "accepted_latch": accepted_latch,
        "reason": "ok" if accepted else "snapshot_not_accepted",
    }


def _current_state_value(sm: Any) -> str:
    try:
        state = sm.get_current_state()
    except Exception:
        state = getattr(sm, "_current_state", "unknown")
    return str(getattr(state, "value", state) or "unknown")


def _commit_once(sm: Any, meta: dict[str, Any]) -> bool:
    commit = getattr(sm, "commit_activation", None)
    if not callable(commit):
        logger.warning(
            "ACTIVATION_PENDING_COMMIT_MONITOR commit_activation unavailable"
        )
        return False
    cycle_capital = {
        "snapshot_source": "capital_authority",
        "ca_valid_brokers": max(1, int(meta.get("registered_brokers") or 0)),
        "aggregation_normalized": True,
        "capital_hydrated": bool(meta.get("hydrated")),
        "ca_not_stale": not bool(meta.get("stale")),
        "real_capital": float(meta.get("real_capital") or 0.0),
    }
    logger.critical(
        "ACTIVATION_PENDING_COMMIT_MONITOR_ATTEMPT state=%s capital=$%.2f "
        "brokers=%s accepted_latch=%s",
        _current_state_value(sm),
        float(meta.get("real_capital") or 0.0),
        meta.get("registered_brokers"),
        meta.get("accepted_latch"),
    )
    try:
        ok = bool(commit(cycle_capital=cycle_capital))
    except Exception as exc:
        logger.warning(
            "ACTIVATION_PENDING_COMMIT_MONITOR commit_activation raised: %s",
            exc,
        )
        return False
    logger.critical(
        "ACTIVATION_PENDING_COMMIT_MONITOR_RESULT ok=%s state=%s",
        ok,
        _current_state_value(sm),
    )
    return ok


def _monitor() -> None:
    interval = max(
        0.5,
        float(
            os.environ.get(
                "NIJA_ACTIVATION_PENDING_COMMIT_INTERVAL_S", "2"
            )
            or 2.0
        ),
    )
    warn_every = max(
        5.0,
        float(
            os.environ.get(
                "NIJA_ACTIVATION_PENDING_COMMIT_LOG_INTERVAL_S", "15"
            )
            or 15.0
        ),
    )
    timeout_s = max(
        30.0,
        float(
            os.environ.get(
                "NIJA_ACTIVATION_PENDING_COMMIT_MONITOR_TIMEOUT_S", "420"
            )
            or 420.0
        ),
    )
    deadline = time.monotonic() + timeout_s
    last_log = 0.0
    logger.warning(
        "ACTIVATION_PENDING_COMMIT_MONITOR_STARTED interval_s=%.1f timeout_s=%.1f",
        interval,
        timeout_s,
    )
    while time.monotonic() < deadline:
        try:
            if not _live_mode():
                time.sleep(interval)
                continue
            sm = _state_machine()
            if sm is None:
                time.sleep(interval)
                continue
            state = _current_state_value(sm)
            if state == "LIVE_ACTIVE":
                logger.warning(
                    "ACTIVATION_PENDING_COMMIT_MONITOR_COMPLETE state=LIVE_ACTIVE"
                )
                return
            if state != "LIVE_PENDING_CONFIRMATION":
                now = time.time()
                if now - last_log >= warn_every:
                    logger.warning(
                        "ACTIVATION_PENDING_COMMIT_MONITOR_WAITING "
                        "reason=state_not_pending state=%s",
                        state,
                    )
                    last_log = now
                time.sleep(interval)
                continue
            accepted, meta = _capital_ready_snapshot()
            if not accepted:
                now = time.time()
                if now - last_log >= warn_every:
                    logger.warning(
                        "ACTIVATION_PENDING_COMMIT_MONITOR_WAITING reason=%s "
                        "hydrated=%s capital=$%.2f stale=%s brokers=%s",
                        meta.get("reason"),
                        meta.get("hydrated"),
                        float(meta.get("real_capital") or 0.0),
                        meta.get("stale"),
                        meta.get("registered_brokers"),
                    )
                    last_log = now
                time.sleep(interval)
                continue
            if _commit_once(sm, meta):
                return
            time.sleep(interval)
        except Exception as exc:
            logger.exception(
                "ACTIVATION_PENDING_COMMIT_MONITOR_ERROR err=%s", exc
            )
            time.sleep(interval)
    logger.warning(
        "ACTIVATION_PENDING_COMMIT_MONITOR_TIMEOUT timeout_s=%.1f", timeout_s
    )


def install_import_hook() -> None:
    """Start only lightweight monitors; never install runtime modules inline."""

    _install_venue_bind_log_filter()
    with _PROCESS_LOCK:
        if not getattr(
            builtins, "_NIJA_ACTIVATION_PENDING_MONITOR_STARTED_20260711c", False
        ):
            setattr(
                builtins,
                "_NIJA_ACTIVATION_PENDING_MONITOR_STARTED_20260711c",
                True,
            )
            thread = threading.Thread(
                target=_monitor,
                name="activation-pending-commit-monitor",
                daemon=True,
            )
            thread.start()
            logger.warning(
                "ACTIVATION_PENDING_COMMIT_MONITOR_INSTALL_COMPLETE "
                "marker=%s thread_alive=%s",
                _MARKER,
                thread.is_alive(),
            )

        if not getattr(
            builtins, "_NIJA_STARTUP_REPAIR_WORKER_STARTED_20260711c", False
        ):
            setattr(
                builtins,
                "_NIJA_STARTUP_REPAIR_WORKER_STARTED_20260711c",
                True,
            )
            repair_thread = threading.Thread(
                target=_startup_repairs_worker,
                name="startup-execution-repairs",
                daemon=True,
            )
            repair_thread.start()
            logger.warning(
                "STARTUP_EXECUTION_REPAIRS_WORKER_STARTED marker=%s "
                "thread_alive=%s synchronous_imports=false",
                _MARKER,
                repair_thread.is_alive(),
            )


__all__ = [
    "install_import_hook",
    "ensure_startup_execution_repairs_ready",
    "_install_startup_execution_repairs",
    "_install_final_stage_venue_routing_repair",
    "_state_machine",
    "_capital_ready_snapshot",
]
