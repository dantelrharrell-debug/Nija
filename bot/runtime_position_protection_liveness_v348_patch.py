"""Authoritative position/protection liveness convergence v348.

Production after v347 showed v346 installed but connected platform Coinbase and
Kraken snapshots could still age past the unchanged 90s authoritative TTL while
v285 reported ``platform_refresh_workers=0``. The cause is wrapper ordering at
the v108 discovery boundary: later convergence patches can replace the discovery
callable after v346 patched v285's candidate helper.

v348 repairs the terminal dispatch boundary without weakening readiness:

* v108 discovery is reasserted to UNION its existing result with v285's current
  strong-proof candidates. A stale/missing connected platform snapshot is
  therefore visible to the actual authoritative worker regardless of wrapper
  install order.
* current authoritative snapshots are also scheduled for proactive refresh at
  v285's existing refresh interval (55% of the unchanged snapshot TTL). This
  gives the same bounded authoritative worker time to complete before the 90s
  readiness TTL expires instead of waiting for readiness to fail first.
* when a refresh candidate exists and no v108 worker owns that exact
  manager/broker key, v348 starts the EXISTING v108 authoritative reconciliation
  worker. It never performs broker reads itself and never grants readiness.
* a Kraken v288 bulk trade-history cost-basis flight that remains unfinished
  past a bounded stale threshold may be retired exactly once per broker. The
  next normal reconciliation may then start one fresh authenticated read. A
  second retirement is forbidden until a newer genuine v288 cache result proves
  recovery.
* after authoritative position recovery, v281 remains the sole owner of
  stop-loss, take-profit, trailing take-profit, trailing-stop and auto-exit
  protection adoption. v348 only wakes/audits the existing coverage path.

No snapshot TTL is extended, no stale snapshot is promoted, no position or cost
basis is fabricated, no trade is forced, and no writer/nonce/risk/capital/
kill-switch/ECEL/minimum/order/fill gate is bypassed.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
import time
from functools import wraps
from typing import Any

LOGGER = logging.getLogger("nija.runtime_position_protection_liveness_v348")
MARKER = "20260902-runtime-position-protection-liveness-v348"
RELEASE_ID = "20260902-runtime-convergence-v348"
_READY_FLAG = "NIJA_RUNTIME_POSITION_PROTECTION_LIVENESS_V348_READY"
_DISCOVERY_PATCH = "_nija_v348_terminal_stale_platform_discovery"
_LOCK = threading.RLock()
_THREAD: threading.Thread | None = None
_COST_BASIS_ESCAPE: dict[int, float] = {}


def _proactive_platform_candidates(manager: Any) -> list[tuple[str, Any]]:
    """Return connected platform brokers whose current snapshot is due refresh."""
    found: list[tuple[str, Any]] = []
    try:
        v285 = importlib.import_module("bot.runtime_authoritative_position_coverage_v285_patch")
        interval_fn = getattr(v285, "_refresh_interval_s", None)
        refresh_after_s = float(interval_fn()) if callable(interval_fn) else 49.5
        refresh_after_s = max(10.0, refresh_after_s)
        platform = getattr(manager, "platform_brokers", {}) or {}
        if callable(platform):
            platform = platform()
        for broker_type, broker in dict(platform or {}).items():
            if broker is None:
                continue
            connected = getattr(broker, "connected", False)
            try:
                connected = connected() if callable(connected) else connected
            except Exception:
                connected = False
            if not bool(connected):
                continue
            if getattr(broker, "_nija_authoritative_position_snapshot_fetch_ok_v285", None) is not True:
                continue
            try:
                at = float(getattr(broker, "_nija_authoritative_position_snapshot_at_monotonic_v285", 0.0) or 0.0)
            except (TypeError, ValueError):
                at = 0.0
            if at <= 0.0:
                continue
            age_s = max(0.0, time.monotonic() - at)
            if age_s < refresh_after_s:
                continue
            raw_name = getattr(broker_type, "value", broker_type)
            name = str(raw_name or "unknown").strip().lower()
            if "." in name:
                name = name.rsplit(".", 1)[-1]
            found.append((name or "unknown", broker))
            LOGGER.info(
                "POSITION_REFRESH_V348_PROACTIVE_DUE marker=%s broker=%s age_s=%.3f refresh_after_s=%.3f "
                "snapshot_ttl_unchanged=true readiness_granted=false",
                MARKER, name or "unknown", age_s, refresh_after_s,
            )
    except Exception:
        return []
    return found


def _candidate_union(manager: Any, existing: list[tuple[str, Any]] | None = None) -> list[tuple[str, Any]]:
    """Union v108, v285 stale/missing, and proactive refresh candidates."""
    found: list[tuple[str, Any]] = list(existing or [])
    seen = {id(broker) for _name, broker in found if broker is not None}
    try:
        v285 = importlib.import_module("bot.runtime_authoritative_position_coverage_v285_patch")
        resolver = getattr(v285, "_platform_candidates", None)
        extra = list(resolver(manager) or []) if callable(resolver) else []
    except Exception:
        extra = []

    for name, broker in extra + _proactive_platform_candidates(manager):
        if broker is None or id(broker) in seen:
            continue
        found.append((str(name or "unknown").strip().lower(), broker))
        seen.add(id(broker))
    return found


def _kraken_bulk_stale_after_s() -> float:
    try:
        value = float(os.environ.get("NIJA_KRAKEN_BULK_ENTRY_PRICE_STALE_FLIGHT_S", "90") or 90.0)
    except (TypeError, ValueError):
        value = 90.0
    return max(30.0, min(300.0, value))


def _recover_stale_kraken_cost_basis_flights() -> int:
    """Retire at most one stale v288 bulk history flight per broker until recovery."""
    try:
        v288 = importlib.import_module("bot.runtime_kraken_cost_basis_bulk_v288_patch")
        flights = getattr(v288, "_BULK_FLIGHTS", None)
        cache = getattr(v288, "_BULK_CACHE", None)
        lock = getattr(v288, "_FLIGHT_LOCK", None)
        if not isinstance(flights, dict) or not isinstance(cache, dict) or lock is None:
            return 0
    except Exception:
        return 0

    retired = 0
    now = time.monotonic()
    stale_after_s = _kraken_bulk_stale_after_s()
    try:
        with lock:
            for key, escaped_at in list(_COST_BASIS_ESCAPE.items()):
                row = cache.get(key)
                try:
                    stored_at = float((row or {}).get("stored_at", 0.0) or 0.0) if isinstance(row, dict) else 0.0
                except (TypeError, ValueError):
                    stored_at = 0.0
                if stored_at > escaped_at:
                    _COST_BASIS_ESCAPE.pop(key, None)
                    LOGGER.critical(
                        "KRAKEN_COST_BASIS_V348_STALE_FLIGHT_RECOVERED marker=%s broker_key=%s "
                        "genuine_cache_newer_than_escape=true synthetic_entry=false safety_gates_bypassed=false",
                        MARKER, key,
                    )

            for key, flight in list(flights.items()):
                if key in _COST_BASIS_ESCAPE or not isinstance(flight, dict):
                    continue
                event = flight.get("event")
                if event is not None and bool(getattr(event, "is_set", lambda: False)()):
                    continue
                try:
                    started_at = float(flight.get("started_at", 0.0) or 0.0)
                except (TypeError, ValueError):
                    started_at = 0.0
                if started_at <= 0.0:
                    continue
                age_s = max(0.0, now - started_at)
                if age_s < stale_after_s:
                    continue
                if flights.get(key) is not flight:
                    continue
                flights.pop(key, None)
                _COST_BASIS_ESCAPE[key] = now
                retired += 1
                LOGGER.critical(
                    "KRAKEN_COST_BASIS_V348_STALE_FLIGHT_ESCAPE marker=%s broker_key=%s age_s=%.1f stale_after_s=%.1f "
                    "single_escape_until_genuine_cache=true old_worker_result_not_promoted=true cost_basis_verified=false "
                    "current_price_fallback=false forced_trade=false safety_gates_bypassed=false",
                    MARKER, key, age_s, stale_after_s,
                )
    except Exception:
        return retired
    return retired


def _patch_v108_discovery() -> bool:
    """Reassert authoritative refresh discovery at the terminal v108 boundary."""
    v108 = importlib.import_module("bot.platform_position_sync_v108_patch")
    current = getattr(v108, "_connected_unsynced_platform_brokers", None)
    if not callable(current):
        return False
    if bool(getattr(current, _DISCOVERY_PATCH, False)):
        return True

    @wraps(current)
    def discovery_v348(manager: Any) -> list[tuple[str, Any]]:
        try:
            base = list(current(manager) or [])
        except Exception:
            base = []
        union = _candidate_union(manager, base)
        if len(union) > len(base):
            LOGGER.info(
                "POSITION_REFRESH_V348_DISCOVERY_RESTORED marker=%s base=%d union=%d "
                "v285_strong_proof_or_proactive_due=true stale_promoted=false readiness_granted=false",
                MARKER, len(base), len(union),
            )
        return union

    setattr(discovery_v348, _DISCOVERY_PATCH, True)
    setattr(discovery_v348, "__wrapped__", current)
    v108._connected_unsynced_platform_brokers = discovery_v348
    return True


def _dispatch_authoritative_workers() -> int:
    """Start only the existing v108 worker for uncovered refresh candidates."""
    try:
        v161 = importlib.import_module("bot.runtime_capital_position_convergence_v161_patch")
        manager_fn = getattr(v161, "_canonical_manager", None)
        manager = manager_fn() if callable(manager_fn) else None
        if manager is None:
            return 0
        v108 = importlib.import_module("bot.platform_position_sync_v108_patch")
        worker = getattr(v108, "_worker", None)
        active = getattr(v108, "_ACTIVE", None)
        lock = getattr(v108, "_LOCK", None)
        discover = getattr(v108, "_connected_unsynced_platform_brokers", None)
        if not callable(worker) or not callable(discover) or not isinstance(active, set) or lock is None:
            return 0
        candidates = list(discover(manager) or [])
    except Exception:
        return 0

    started = 0
    for broker_name, broker in candidates:
        if broker is None:
            continue
        key = (id(manager), id(broker))
        claimed = False
        try:
            with lock:
                if key not in active:
                    active.add(key)
                    claimed = True
        except Exception:
            claimed = False
        if not claimed:
            continue
        try:
            thread = threading.Thread(
                target=worker,
                args=(manager, str(broker_name or "unknown"), broker, key, "v348_authoritative_snapshot_refresh"),
                name=f"V348PositionRefresh-{str(broker_name or 'unknown')}",
                daemon=True,
            )
            thread.start()
            started += 1
            LOGGER.critical(
                "POSITION_REFRESH_V348_WORKER_STARTED marker=%s broker=%s key=%s "
                "existing_v108_worker=true authoritative_fetch_required=true proactive_before_ttl=true "
                "readiness_granted=false snapshot_ttl_unchanged=true synthetic_success=false safety_gates_bypassed=false",
                MARKER, str(broker_name or "unknown"), key,
            )
        except Exception as exc:
            try:
                with lock:
                    active.discard(key)
            except Exception:
                pass
            LOGGER.warning(
                "POSITION_REFRESH_V348_WORKER_START_FAILED marker=%s broker=%s error=%s:%s trading_fail_closed=true",
                MARKER, str(broker_name or "unknown"), type(exc).__name__, exc,
            )
    return started


def _wake_coverage_and_activation() -> None:
    """Wake existing owners only; never publish readiness here."""
    try:
        v231 = importlib.import_module("bot.runtime_authority_nonce_truth_convergence_v231_patch")
        wake = getattr(v231, "_wake_position_sync_if_needed", None)
        if callable(wake):
            wake()
    except Exception:
        pass
    try:
        v347 = importlib.import_module("bot.runtime_execution_activation_protection_v347_patch")
        audit = getattr(v347, "_audit_protective_coverage", None)
        wake_exec = getattr(v347, "_wake_activation", None)
        if callable(audit):
            audit()
        if callable(wake_exec):
            wake_exec()
    except Exception:
        pass


def _register_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_position_protection_liveness_v348"] = _READY_FLAG
        return True
    except Exception:
        return False


def _worker_loop() -> None:
    while True:
        try:
            _recover_stale_kraken_cost_basis_flights()
            _patch_v108_discovery()
            _dispatch_authoritative_workers()
            _wake_coverage_and_activation()
        except Exception:
            LOGGER.debug("v348 worker pulse failed", exc_info=True)
        time.sleep(3.0)


def install_import_hook() -> bool:
    global _THREAD
    with _LOCK:
        discovery_ready = manifest_ready = False
        try:
            discovery_ready = _patch_v108_discovery()
            manifest_ready = _register_manifest()
        except Exception as exc:
            LOGGER.exception(
                "RUNTIME_POSITION_PROTECTION_LIVENESS_V348_INSTALL_ERROR marker=%s error=%s:%s fail_closed=true",
                MARKER, type(exc).__name__, exc,
            )
        ready = bool(discovery_ready and manifest_ready)
        os.environ[_READY_FLAG] = "1" if ready else "0"
        if ready:
            _recover_stale_kraken_cost_basis_flights()
            _dispatch_authoritative_workers()
            _wake_coverage_and_activation()
            if _THREAD is None or not _THREAD.is_alive():
                _THREAD = threading.Thread(target=_worker_loop, name="PositionProtectionLivenessV348", daemon=True)
                _THREAD.start()
        log = LOGGER.critical if ready else LOGGER.error
        log(
            "RUNTIME_POSITION_PROTECTION_LIVENESS_V348_%s marker=%s ready=%s "
            "terminal_v108_discovery=%s manifest=%s authoritative_worker_only=true proactive_refresh_before_ttl=true "
            "kraken_bulk_cost_basis_single_stale_escape=true take_profit_owner=v281 stop_loss_owner=v281 "
            "trailing_take_profit_owner=v281 trailing_stop_owner=v281 auto_exit_reconciler_owner=v281 dust_policy_unchanged=true "
            "snapshot_ttl_unchanged=true stale_promoted=false execution_marker_policy_unchanged=true "
            "forced_trade=false forced_activation=false position_success_fabricated=false cost_basis_fabricated=false "
            "writer_nonce_capital_risk_killswitch_ecel_minimum_quantity_order_fill_gates_unchanged=true "
            "safety_gates_bypassed=false",
            "READY" if ready else "NOT_READY", MARKER, str(ready).lower(),
            str(discovery_ready).lower(), str(manifest_ready).lower(),
        )
        return ready


def install() -> bool:
    return install_import_hook()


__all__ = ["MARKER", "RELEASE_ID", "install", "install_import_hook"]
