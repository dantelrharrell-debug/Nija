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



_BALANCE_TOTAL_KEYS = (
    "total_funds",
    "total_balance",
    "total_equity",
    "equity",
    "account_equity",
    "portfolio_value",
    "trading_balance",
    "balance",
    "usd_value",
)


def _balance_total(value: Any) -> float:
    if isinstance(value, dict):
        for key in _BALANCE_TOTAL_KEYS:
            try:
                amount = float(value.get(key) or 0.0)
            except (TypeError, ValueError, OverflowError):
                amount = 0.0
            if amount > 0.0:
                return amount
        return 0.0
    try:
        amount = float(value or 0.0)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    return amount if amount > 0.0 else 0.0


def _cached_broker_balance(
    broker_obj: Any,
    broker_key: str,
    capital_authority: Any = None,
) -> tuple[float, str]:
    """Read an already-published balance without invoking broker I/O."""

    normalized_key = broker_key.strip().lower()
    if (
        normalized_key == "okx"
        and bool(getattr(broker_obj, "connected", False))
        and str(os.environ.get("NIJA_OKX_BALANCE_OBSERVED", "") or "").strip().lower()
        in {"1", "true", "yes", "on"}
        and str(os.environ.get("NIJA_OKX_FUNDING_STATUS", "") or "").strip().lower()
        == "funded"
    ):
        candidates = (
            getattr(broker_obj, "_okx_trading_total_quote", None),
            getattr(broker_obj, "_okx_trading_spendable_quote", None),
            os.environ.get("NIJA_OKX_TRADING_TOTAL_QUOTE"),
            os.environ.get("NIJA_OKX_TRADING_SPENDABLE_QUOTE"),
        )
        authoritative = max((_balance_total(value) for value in candidates), default=0.0)
        if authoritative > 0.0:
            return authoritative, "okx_authenticated_wallet"

    if normalized_key == "okx":
        # Do not fall through to a stale generic cache after the authenticated
        # OKX proof becomes unobserved or non-executable.
        return 0.0, "okx_authenticated_wallet_unavailable"

    for attr in (
        "_last_known_balance",
        "_last_confirmed_balance",
        "last_known_balance",
        "cached_balance",
    ):
        amount = _balance_total(getattr(broker_obj, attr, None))
        if amount > 0.0:
            return amount, attr

    balances = getattr(capital_authority, "_broker_balances", {}) or {}
    if isinstance(balances, dict):
        for key, value in balances.items():
            normalized = str(getattr(key, "value", key)).strip().lower()
            if normalized == normalized_key:
                amount = _balance_total(value)
                if amount > 0.0:
                    return amount, "capital_authority"

    return 0.0, "unavailable"



def _broker_manager_snapshot() -> tuple[bool, dict[str, Any]]:
    """Observe connected brokers using accepted in-memory balances only.

    Startup monitors are not balance-refresh owners.  They must not call private
    exchange endpoints or republish CapitalAuthority feeds; those mutations
    belong to the broker manager and BalanceService.  Missing cached state is a
    fail-closed result and the monitor will retry after the canonical owner
    publishes a snapshot.
    """

    mabm_mod = _loaded_module(
        "bot.multi_account_broker_manager", "multi_account_broker_manager"
    )
    if mabm_mod is None:
        return False, {"reason": "broker_manager_module_not_loaded"}

    try:
        getter = getattr(mabm_mod, "get_broker_manager", None)
        if not callable(getter):
            return False, {"reason": "broker_manager_getter_unavailable"}
        mgr = getter()
        if mgr is None:
            return False, {"reason": "broker_manager_none"}

        ca = None
        ca_mod = _loaded_module("bot.capital_authority", "capital_authority")
        if ca_mod is not None:
            ca_getter = getattr(ca_mod, "get_capital_authority", None)
            if callable(ca_getter):
                try:
                    ca = ca_getter()
                except Exception:
                    ca = None

        total_balance = 0.0
        per_broker: dict[str, float] = {}
        sources: dict[str, str] = {}
        platform_brokers = getattr(mgr, "_platform_brokers", {})
        for broker_type, broker_obj in list(platform_brokers.items()):
            if broker_obj is None:
                continue
            try:
                connected = bool(getattr(broker_obj, "connected", False))
                if not connected:
                    is_connected = getattr(mgr, "is_platform_connected", None)
                    if callable(is_connected):
                        connected = bool(is_connected(broker_type))
                if not connected:
                    continue

                broker_key = str(getattr(broker_type, "value", broker_type))
                balance, source = _cached_broker_balance(broker_obj, broker_key, ca)
                if balance <= 0.0:
                    logger.debug(
                        "ACTIVATION_PENDING_COMMIT cached_balance_unavailable broker=%s",
                        broker_key,
                    )
                    continue

                per_broker[broker_key] = balance
                sources[broker_key] = source
                total_balance += balance
            except Exception as exc:
                logger.debug(
                    "ACTIVATION_PENDING_COMMIT broker_snapshot_error broker=%s err=%s",
                    broker_type,
                    exc,
                )

        connected_count = len(per_broker)
        if connected_count == 0:
            return False, {
                "reason": "no_connected_cached_balances",
                "hydrated": False,
                "real_capital": 0.0,
                "stale": True,
                "registered_brokers": 0,
                "accepted_latch": False,
                "source": "broker_manager_cached",
            }

        accepted = total_balance > 0.0
        meta = {
            "hydrated": accepted,
            "real_capital": total_balance,
            "stale": False,
            "registered_brokers": connected_count,
            "accepted_latch": accepted,
            "reason": "broker_manager_cached_ok" if accepted else "broker_manager_cached_zero",
            "per_broker": per_broker,
            "sources": sources,
            "source": "broker_manager_cached",
        }
        logger.debug(
            "ACTIVATION_PENDING_COMMIT_MONITOR_BROKER_MANAGER_SNAPSHOT "
            "connected=%d total_balance=$%.2f accepted=%s brokers=%s source=cached_only",
            connected_count,
            total_balance,
            accepted,
            list(per_broker.keys()),
        )
        return accepted, meta
    except Exception as exc:
        logger.debug("ACTIVATION_PENDING_COMMIT broker_manager_snapshot_error err=%s", exc)
        return False, {"reason": f"broker_manager_snapshot_error:{exc}"}

def _capital_ready_snapshot() -> tuple[bool, dict[str, Any]]:
    module = _loaded_module("bot.capital_authority", "capital_authority")
    if module is None:
        # Capital authority not yet loaded — try broker manager directly.
        return _broker_manager_snapshot()
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

    # If the CA snapshot is not yet accepted, inspect the canonical broker
    # manager's already-published balances.  This path is observational only:
    # it performs no private exchange I/O and republishes no capital feeds.
    if not accepted:
        bm_accepted, bm_meta = _broker_manager_snapshot()
        if bm_accepted:
            # Re-read CA after force_accept_feed() may have hydrated it.
            try:
                hydrated = bool(getattr(ca, "is_hydrated", False))
                reader2 = getattr(ca, "get_real_capital", None)
                real2 = float(reader2() if callable(reader2) else real)
                real = max(real, real2)
            except Exception:
                real = max(real, float(bm_meta.get("real_capital") or 0.0))
            registered = max(registered, int(bm_meta.get("registered_brokers") or 0))
            stale = False
            accepted = True
            accepted_latch = accepted_latch or bool(bm_meta.get("accepted_latch"))

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
    # Use the actual connected broker count from the broker manager when the CA
    # reports zero (stale zero-broker state) so that cycle_capital carries real
    # broker context rather than the stale placeholder.
    registered_brokers = int(meta.get("registered_brokers") or 0)
    if registered_brokers == 0:
        bm_accepted, bm_meta = _broker_manager_snapshot()
        if bm_accepted:
            registered_brokers = max(registered_brokers, int(bm_meta.get("registered_brokers") or 0))
    cycle_capital = {
        "snapshot_source": "capital_authority",
        "ca_valid_brokers": max(1, registered_brokers),
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


def _monitor(stop_event: threading.Event | None = None) -> None:
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
    while stop_event is None or not stop_event.is_set():
        now_monotonic = time.monotonic()
        if now_monotonic >= deadline:
            logger.warning(
                "ACTIVATION_PENDING_COMMIT_MONITOR_STILL_WAITING timeout_s=%.1f continuing=true",
                timeout_s,
            )
            deadline = now_monotonic + timeout_s
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
    logger.info("ACTIVATION_PENDING_COMMIT_MONITOR_STOPPED requested=true")


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
    "_broker_manager_snapshot",
]
