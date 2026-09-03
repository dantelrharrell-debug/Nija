"""Authoritative position/protection liveness convergence v348.

Production after v347 showed v346 installed but connected platform Coinbase and
Kraken snapshots could still age past the unchanged 90s authoritative TTL while
v285 reported ``platform_refresh_workers=0``.  The cause is wrapper ordering at
the v108 discovery boundary: later convergence patches can replace the discovery
callable after v346 patched v285's candidate helper.

v348 repairs the terminal dispatch boundary without weakening readiness:

* v108 discovery is reasserted to UNION its existing result with v285's current
  strong-proof candidates.  A stale/missing connected platform snapshot is
  therefore visible to the actual authoritative worker regardless of wrapper
  install order.
* when stale candidates exist and no v108 worker owns that exact manager/broker
  key, v348 starts the EXISTING v108 authoritative reconciliation worker.  It
  never performs broker reads itself and never grants readiness.
* after authoritative position recovery, v281 remains the sole owner of
  stop-loss, take-profit, trailing take-profit, trailing-stop and auto-exit
  protection adoption.  v348 only wakes/audits the existing coverage path.
* the genuine execution marker policy from v346/v347 is unchanged: no ACK,
  connected state, requested notional, market price, stale fill, or writer
  heartbeat can satisfy execution_ready.

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


def _candidate_union(manager: Any, existing: list[tuple[str, Any]] | None = None) -> list[tuple[str, Any]]:
    """Union current v108 results with v285 strong-proof candidates."""
    found: list[tuple[str, Any]] = list(existing or [])
    seen = {id(broker) for _name, broker in found if broker is not None}
    try:
        v285 = importlib.import_module("bot.runtime_authoritative_position_coverage_v285_patch")
        resolver = getattr(v285, "_platform_candidates", None)
        if not callable(resolver):
            return found
        extra = list(resolver(manager) or [])
    except Exception:
        return found

    for name, broker in extra:
        if broker is None or id(broker) in seen:
            continue
        found.append((str(name or "unknown").strip().lower(), broker))
        seen.add(id(broker))
    return found


def _patch_v108_discovery() -> bool:
    """Reassert stale/missing strong-proof discovery at the terminal v108 boundary."""
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
                "v285_strong_proof_only=true stale_promoted=false readiness_granted=false",
                MARKER, len(base), len(union),
            )
        return union

    setattr(discovery_v348, _DISCOVERY_PATCH, True)
    setattr(discovery_v348, "__wrapped__", current)
    v108._connected_unsynced_platform_brokers = discovery_v348
    return True


def _dispatch_authoritative_workers() -> int:
    """Start only the existing v108 worker for uncovered stale candidates."""
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
                args=(manager, str(broker_name or "unknown"), broker, key, "v348_stale_snapshot_recovery"),
                name=f"V348PositionRefresh-{str(broker_name or 'unknown')}",
                daemon=True,
            )
            thread.start()
            started += 1
            LOGGER.critical(
                "POSITION_REFRESH_V348_WORKER_STARTED marker=%s broker=%s key=%s "
                "existing_v108_worker=true authoritative_fetch_required=true readiness_granted=false "
                "snapshot_ttl_unchanged=true synthetic_success=false safety_gates_bypassed=false",
                MARKER, str(broker_name or "unknown"), key,
            )
        except Exception as exc:
            try:
                with lock:
                    active.discard(key)
            except Exception:
                pass
            LOGGER.warning(
                "POSITION_REFRESH_V348_WORKER_START_FAILED marker=%s broker=%s error=%s:%s "
                "trading_fail_closed=true",
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
            _dispatch_authoritative_workers()
            _wake_coverage_and_activation()
            if _THREAD is None or not _THREAD.is_alive():
                _THREAD = threading.Thread(target=_worker_loop, name="PositionProtectionLivenessV348", daemon=True)
                _THREAD.start()
        log = LOGGER.critical if ready else LOGGER.error
        log(
            "RUNTIME_POSITION_PROTECTION_LIVENESS_V348_%s marker=%s ready=%s "
            "terminal_v108_discovery=%s manifest=%s authoritative_worker_only=true "
            "take_profit_owner=v281 stop_loss_owner=v281 trailing_take_profit_owner=v281 "
            "trailing_stop_owner=v281 auto_exit_reconciler_owner=v281 dust_policy_unchanged=true "
            "snapshot_ttl_unchanged=true stale_promoted=false execution_marker_policy_unchanged=true "
            "forced_trade=false forced_activation=false position_success_fabricated=false "
            "writer_nonce_capital_risk_killswitch_ecel_minimum_quantity_order_fill_gates_unchanged=true "
            "safety_gates_bypassed=false",
            "READY" if ready else "NOT_READY", MARKER, str(ready).lower(),
            str(discovery_ready).lower(), str(manifest_ready).lower(),
        )
        return ready


def install() -> bool:
    return install_import_hook()


__all__ = ["MARKER", "RELEASE_ID", "install", "install_import_hook"]
