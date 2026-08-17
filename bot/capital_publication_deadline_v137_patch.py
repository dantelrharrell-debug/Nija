"""Pre-expiry capital publication refresh convergence v137.

Production v135/v136 showed a remaining liveness gap: the immutable
CapitalAuthority publication could reach its 90-second expiry before the runtime
watchdog started a replacement refresh.  v133 then correctly revoked live
execution.  A second issue allowed concurrent/failed coordinator refreshes to
fall through the MABM legacy path, which could update legacy capital timestamps
without renewing the immutable publication proof.

v137 keeps the strict expiry contract and fixes scheduling/consumer behavior:

* schedule a canonical coordinator refresh while the current publication is
  still valid, with headroom derived from the bounded v78 fetch budget plus the
  watchdog cadence;
* use only the existing CapitalRefreshCoordinator as the proactive writer;
* coalesce MABM refresh calls while that coordinator is already in flight rather
  than letting a duplicate call fall through to legacy CapitalAuthority writes;
* clamp any MABM refresh result to not-ready when the immutable publication is
  rejected, missing, or expired;
* never extend publication expiry, synthesize freshness, force activation,
  alter nonce/writer ownership, clear a kill switch, or bypass risk gates.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
import time
from datetime import datetime, timezone
from functools import wraps
from types import ModuleType
from typing import Any

LOGGER = logging.getLogger("nija.capital_publication_deadline_v137")
MARKER = "20260817-capital-publication-deadline-v137"
RELEASE_ID = "20260817-runtime-convergence-v137"
_FLAG = "NIJA_CAPITAL_PUBLICATION_DEADLINE_V137_INSTALLED"
_PATCH_ATTR = "_nija_capital_publication_deadline_v137"
_LOCK = threading.RLock()
_INSTALLED = False


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "enabled", "y"}


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _capital_authority_module() -> ModuleType:
    for name in ("bot.capital_authority", "capital_authority"):
        try:
            return importlib.import_module(name)
        except ImportError:
            continue
    raise ImportError("capital_authority unavailable")


def _authority() -> Any:
    module = _capital_authority_module()
    getter = getattr(module, "get_capital_authority", None)
    if not callable(getter):
        raise RuntimeError("get_capital_authority unavailable")
    return getter()


def _freshness_ttl_seconds() -> float:
    try:
        module = _capital_authority_module()
        canonical = float(getattr(module, "_DEFAULT_FRESHNESS_TTL_S", 90.0) or 90.0)
    except Exception:
        canonical = 90.0
    try:
        configured = float(os.environ.get("NIJA_CAPITAL_FRESHNESS_TTL_S", canonical) or canonical)
    except (TypeError, ValueError):
        configured = canonical
    # Never broaden the canonical authority TTL from this convergence layer.
    return max(10.0, min(canonical, configured))


def _fetch_budget_seconds() -> float:
    try:
        module = importlib.import_module("bot.capital_refresh_live_continuity_v78_patch")
        getter = getattr(module, "fetch_budget_seconds", None)
        if callable(getter):
            return max(5.0, float(getter()))
    except Exception:
        pass
    return 50.0


def _refresh_headroom_seconds(manager: Any) -> float:
    """Return how early a refresh must start before immutable publication expiry."""
    ttl_s = _freshness_ttl_seconds()
    try:
        cadence_s = max(1.0, float(getattr(manager, "capital_watchdog_interval_s", 10.0) or 10.0))
    except (TypeError, ValueError):
        cadence_s = 10.0
    default = _fetch_budget_seconds() + max(5.0, cadence_s)
    raw = str(os.environ.get("NIJA_CAPITAL_PUBLICATION_REFRESH_HEADROOM_S", "") or "").strip()
    if raw:
        try:
            requested = float(raw)
        except (TypeError, ValueError):
            requested = default
    else:
        requested = default
    # Preserve at least five seconds of immutable-validity margin.  This only
    # moves refresh earlier; it never changes the publication's expiry itself.
    ceiling = max(5.0, ttl_s - 5.0)
    return max(5.0, min(requested, ceiling))


def _publication_meta(authority: Any, *, now: datetime | None = None) -> tuple[bool, dict[str, Any]]:
    current_time = _utc(now) or datetime.now(timezone.utc)
    getter = getattr(authority, "get_snapshot_publication_status", None)
    if not callable(getter):
        return False, {
            "accepted": False,
            "stale": True,
            "reason": "publication_status_unavailable",
            "remaining_s": 0.0,
        }
    try:
        status = getter()
    except Exception as exc:
        return False, {
            "accepted": False,
            "stale": True,
            "reason": f"publication_status_error:{type(exc).__name__}:{exc}",
            "remaining_s": 0.0,
        }
    if status is None:
        return False, {
            "accepted": False,
            "stale": True,
            "reason": "publication_status_missing",
            "remaining_s": 0.0,
        }

    accepted = bool(getattr(status, "accepted", False))
    stale = bool(getattr(status, "stale", True))
    reason = str(getattr(status, "reason", "unknown") or "unknown")
    timestamp = _utc(getattr(status, "timestamp", None))
    expiry = _utc(getattr(status, "expiry", None))
    remaining_s = 0.0
    if expiry is None:
        stale = True
        reason = "publication_expiry_missing"
    else:
        remaining_s = (expiry - current_time).total_seconds()
        if remaining_s <= 0.0:
            stale = True
            reason = "expired_after_publish"

    current = bool(accepted and not stale and expiry is not None and remaining_s > 0.0)
    return current, {
        "accepted": accepted,
        "stale": stale,
        "reason": reason,
        "timestamp": timestamp,
        "expiry": expiry,
        "remaining_s": max(0.0, remaining_s),
    }


def _publication_refresh_due(
    authority: Any,
    manager: Any,
    *,
    now: datetime | None = None,
) -> tuple[bool, dict[str, Any]]:
    current, meta = _publication_meta(authority, now=now)
    headroom_s = _refresh_headroom_seconds(manager)
    meta = dict(meta)
    meta["headroom_s"] = headroom_s
    if not current:
        meta["due_reason"] = f"publication_not_current:{meta.get('reason', 'unknown')}"
        return True, meta
    if float(meta.get("remaining_s", 0.0) or 0.0) <= headroom_s:
        meta["due_reason"] = "pre_expiry_headroom"
        return True, meta
    meta["due_reason"] = "not_due"
    return False, meta


def _typed_snapshot(authority: Any) -> Any:
    getter = getattr(authority, "get_typed_snapshot", None)
    if callable(getter):
        try:
            snapshot = getter()
            if snapshot is not None:
                return snapshot
        except Exception:
            pass
    return getattr(authority, "_last_typed_snapshot", None)


def _read_only_result(authority: Any, *, coalesced: bool) -> dict[str, float]:
    current, meta = _publication_meta(authority)
    snapshot = _typed_snapshot(authority) if current else None
    if snapshot is None:
        return {
            "ready": 0.0,
            "total_capital": 0.0,
            "valid_brokers": 0.0,
            "kraken_capital": 0.0,
            "pending": 1.0,
            "publication_current": 0.0,
            "coalesced": 1.0 if coalesced else 0.0,
        }
    balances = dict(getattr(snapshot, "broker_balances", {}) or {})
    total = max(0.0, float(getattr(snapshot, "real_capital", 0.0) or 0.0))
    valid = max(0, int(getattr(snapshot, "broker_count", 0) or 0))
    return {
        "ready": 1.0 if total > 0.0 and valid > 0 else 0.0,
        "total_capital": total,
        "valid_brokers": float(valid),
        "kraken_capital": max(0.0, float(balances.get("kraken", 0.0) or 0.0)),
        "publication_current": 1.0,
        "publication_remaining_s": float(meta.get("remaining_s", 0.0) or 0.0),
        "coalesced": 1.0 if coalesced else 0.0,
    }


def _coordinator_in_flight(manager: Any) -> bool:
    coordinator = getattr(manager, "_capital_coordinator", None)
    return bool(coordinator is not None and getattr(coordinator, "_in_flight", False))


def _has_payload(broker: Any) -> bool:
    if getattr(broker, "_last_known_balance", None) is not None:
        return True
    for name in ("has_balance_payload_for_capital", "has_balance_payload"):
        probe = getattr(broker, name, None)
        if callable(probe):
            try:
                if bool(probe()):
                    return True
            except Exception:
                continue
    return False


def _runtime_broker_map(manager: Any) -> dict[str, Any]:
    brokers: dict[str, Any] = {}
    for broker_type, broker in list(getattr(manager, "_platform_brokers", {}).items()):
        if broker is None or not _has_payload(broker):
            continue
        key = str(getattr(broker_type, "value", broker_type) or "").strip().lower()
        if key:
            brokers[key] = broker

    if _truthy(os.environ.get("NIJA_AGGREGATE_USER_CAPITAL_IN_AUTHORITY", "false")):
        for user_id, user_brokers in list(getattr(manager, "user_brokers", {}).items()):
            for broker_type, broker in list((user_brokers or {}).items()):
                if broker is None or not bool(getattr(broker, "connected", False)):
                    continue
                key = f"{user_id}_{getattr(broker_type, 'value', broker_type)}".strip().lower()
                brokers[key] = broker
    return brokers


def _runtime_schedule_enabled(manager: Any) -> bool:
    registration = getattr(manager, "_broker_registration_complete", None)
    if registration is not None and callable(getattr(registration, "is_set", None)):
        if not registration.is_set():
            return False
    if bool(getattr(manager, "_startup_lock_released", False)):
        return True
    try:
        module = _capital_authority_module()
        getter = getattr(module, "get_startup_lock", None)
        if callable(getter):
            return bool(getter().is_set())
    except Exception:
        pass
    return False


def _execute_deadline_refresh(manager: Any, *, trigger: str = "publication_deadline_v137") -> bool:
    coordinator = getattr(manager, "_capital_coordinator", None)
    if coordinator is None or _coordinator_in_flight(manager):
        return False
    broker_map = _runtime_broker_map(manager)
    if not broker_map:
        LOGGER.warning(
            "CAPITAL_PUBLICATION_DEADLINE_V137_SKIPPED marker=%s reason=no_eligible_brokers",
            MARKER,
        )
        return False

    snapshot = coordinator.execute_refresh(
        broker_map=broker_map,
        trigger=trigger,
        open_exposure_usd=0.0,
    )
    authority = _authority()
    current, meta = _publication_meta(authority)
    if snapshot is None or not current:
        LOGGER.warning(
            "CAPITAL_PUBLICATION_DEADLINE_V137_REFRESH_INCOMPLETE marker=%s "
            "snapshot=%s publication_current=%s reason=%s remaining_s=%.1f",
            MARKER,
            snapshot is not None,
            current,
            meta.get("reason", "unknown"),
            float(meta.get("remaining_s", 0.0) or 0.0),
        )
        return False

    real = max(0.0, float(getattr(snapshot, "real_capital", 0.0) or 0.0))
    valid = max(0, int(getattr(snapshot, "broker_count", 0) or 0))
    state_lock = getattr(manager, "_capital_state_lock", None)
    try:
        if state_lock is not None:
            with state_lock:
                manager._capital_ready = bool(real > 0.0 and valid > 0)
                manager._capital_last_refresh_ts = time.time()
                if valid > 0:
                    manager._capital_last_valid_brokers = valid
        sync = getattr(manager, "_sync_platform_connection_states", None)
        if callable(sync):
            sync(broker_map)
    except Exception as exc:
        LOGGER.debug("v137 manager mirror update failed after canonical publish: %s", exc)

    LOGGER.critical(
        "CAPITAL_PUBLICATION_DEADLINE_V137_REFRESHED marker=%s trigger=%s "
        "real=%.2f brokers=%d remaining_s=%.1f canonical_coordinator_only=true",
        MARKER,
        trigger,
        real,
        valid,
        float(meta.get("remaining_s", 0.0) or 0.0),
    )
    return True


def _start_deadline_monitor(manager: Any) -> bool:
    with _LOCK:
        if bool(getattr(manager, "_nija_capital_publication_deadline_v137_started", False)):
            return True
        setattr(manager, "_nija_capital_publication_deadline_v137_started", True)

    stop_event = getattr(manager, "_capital_watchdog_stop", None)
    if stop_event is None or not callable(getattr(stop_event, "wait", None)):
        stop_event = threading.Event()

    def _monitor() -> None:
        last_reason = ""
        while True:
            try:
                interval_s = max(
                    1.0,
                    min(10.0, float(getattr(manager, "capital_watchdog_interval_s", 10.0) or 10.0)),
                )
            except (TypeError, ValueError):
                interval_s = 10.0
            if stop_event.wait(interval_s):
                return
            try:
                if not _runtime_schedule_enabled(manager):
                    continue
                authority = _authority()
                due, meta = _publication_refresh_due(authority, manager)
                if not due:
                    continue
                reason = str(meta.get("due_reason", "unknown"))
                if reason != last_reason:
                    last_reason = reason
                    LOGGER.info(
                        "CAPITAL_PUBLICATION_DEADLINE_V137_DUE marker=%s reason=%s "
                        "remaining_s=%.1f headroom_s=%.1f coordinator_in_flight=%s",
                        MARKER,
                        reason,
                        float(meta.get("remaining_s", 0.0) or 0.0),
                        float(meta.get("headroom_s", 0.0) or 0.0),
                        _coordinator_in_flight(manager),
                    )
                if _coordinator_in_flight(manager):
                    continue
                _execute_deadline_refresh(manager)
            except Exception as exc:
                LOGGER.warning(
                    "CAPITAL_PUBLICATION_DEADLINE_V137_MONITOR_ERROR marker=%s err=%s:%s",
                    MARKER,
                    type(exc).__name__,
                    exc,
                )

    threading.Thread(
        target=_monitor,
        name="capital-publication-deadline-v137",
        daemon=True,
    ).start()
    LOGGER.critical(
        "CAPITAL_PUBLICATION_DEADLINE_V137_MONITOR_STARTED marker=%s ttl_s=%.1f "
        "fetch_budget_s=%.1f headroom_s=%.1f immutable_expiry_unchanged=true",
        MARKER,
        _freshness_ttl_seconds(),
        _fetch_budget_seconds(),
        _refresh_headroom_seconds(manager),
    )
    return True


def _patch_manager_class(cls: type) -> bool:
    current = getattr(cls, "refresh_capital_authority", None)
    if not callable(current):
        return False
    if getattr(current, _PATCH_ATTR, False):
        return True

    @wraps(current)
    def refresh_capital_authority_v137(self: Any, *args: Any, **kwargs: Any) -> Any:
        trigger = str(kwargs.get("trigger", args[0] if args else "manual") or "manual")
        coordinator = getattr(self, "_capital_coordinator", None)

        # A duplicate call while the canonical writer is active must be read-only.
        # The legacy method's snapshot=None branch can otherwise call
        # CapitalAuthority.refresh()/update(), touching legacy timestamps without
        # renewing the immutable publication proof.
        if coordinator is not None and _coordinator_in_flight(self):
            try:
                result = _read_only_result(_authority(), coalesced=True)
            except Exception:
                result = {
                    "ready": 0.0,
                    "total_capital": 0.0,
                    "valid_brokers": 0.0,
                    "pending": 1.0,
                    "publication_current": 0.0,
                    "coalesced": 1.0,
                }
            LOGGER.info(
                "CAPITAL_PUBLICATION_DEADLINE_V137_COALESCED marker=%s trigger=%s "
                "canonical_writer_in_flight=true legacy_fallback_skipped=true ready=%s",
                MARKER,
                trigger,
                bool(result.get("ready", 0.0)),
            )
            return result

        result = current(self, *args, **kwargs)
        if not isinstance(result, dict):
            return result

        try:
            publication_current, meta = _publication_meta(_authority())
        except Exception as exc:
            publication_current = False
            meta = {"reason": f"publication_check_error:{type(exc).__name__}:{exc}", "remaining_s": 0.0}

        converged = dict(result)
        converged["publication_current"] = 1.0 if publication_current else 0.0
        converged["publication_remaining_s"] = float(meta.get("remaining_s", 0.0) or 0.0)
        if publication_current:
            return converged

        # Immutable publication proof is authoritative.  Never report runtime
        # capital ready solely because a legacy refresh/update returned a value.
        converged["ready"] = 0.0
        converged["publication_fail_closed"] = 1.0
        state_lock = getattr(self, "_capital_state_lock", None)
        try:
            if state_lock is not None:
                with state_lock:
                    self._capital_ready = False
        except Exception:
            pass
        LOGGER.critical(
            "CAPITAL_PUBLICATION_DEADLINE_V137_RESULT_CLAMPED marker=%s trigger=%s "
            "reason=%s legacy_timestamp_not_authoritative=true trading_fail_closed=true",
            MARKER,
            trigger,
            meta.get("reason", "unknown"),
        )
        return converged

    setattr(refresh_capital_authority_v137, _PATCH_ATTR, True)
    setattr(refresh_capital_authority_v137, "_nija_v137_original", current)
    cls.refresh_capital_authority = refresh_capital_authority_v137

    original_start = getattr(cls, "_start_capital_watchdog", None)
    if callable(original_start) and not getattr(original_start, _PATCH_ATTR, False):
        @wraps(original_start)
        def start_watchdog_v137(self: Any, *args: Any, **kwargs: Any) -> Any:
            result = original_start(self, *args, **kwargs)
            _start_deadline_monitor(self)
            return result

        setattr(start_watchdog_v137, _PATCH_ATTR, True)
        cls._start_capital_watchdog = start_watchdog_v137

    LOGGER.critical(
        "CAPITAL_PUBLICATION_DEADLINE_V137_MABM_CONVERGED marker=%s class=%s "
        "inflight_coalesced=true immutable_publication_authoritative=true",
        MARKER,
        cls.__name__,
    )
    return True


def _install_manager_patch() -> bool:
    module = importlib.import_module("bot.multi_account_broker_manager")
    cls = getattr(module, "MultiAccountBrokerManager", None)
    if not isinstance(cls, type):
        return False
    patched = _patch_manager_class(cls)
    manager = getattr(module, "_manager", None)
    if manager is not None:
        _start_deadline_monitor(manager)
    return patched


def install_import_hook() -> bool:
    global _INSTALLED
    with _LOCK:
        ok = _install_manager_patch()
        if not ok:
            raise RuntimeError("v137 could not patch MultiAccountBrokerManager")
        _INSTALLED = True
        os.environ[_FLAG] = "1"
    LOGGER.critical(
        "CAPITAL_PUBLICATION_DEADLINE_V137_INSTALLED marker=%s release=%s "
        "pre_expiry_refresh=true canonical_coordinator_only=true "
        "publication_expiry_extended=false force_live=false risk_gates_unchanged=true "
        "nonce_gates_unchanged=true kill_switch_unchanged=true",
        MARKER,
        RELEASE_ID,
    )
    return True


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER",
    "RELEASE_ID",
    "_publication_meta",
    "_publication_refresh_due",
    "_refresh_headroom_seconds",
    "_runtime_broker_map",
    "_execute_deadline_refresh",
    "_patch_manager_class",
    "install",
    "install_import_hook",
]
