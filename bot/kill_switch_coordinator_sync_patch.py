"""Keep StartupCoordinator kill-switch truth aligned with the canonical KillSwitch.

The canonical kill switch is the safety authority. This patch mirrors its
active/inactive state into StartupCoordinator without clearing the stop,
changing risk gates, or forcing a coordinator lifecycle state. A state change
invalidates any prior activation commit and advances the global epoch so a
fresh activation proof is required after deactivation.

The runtime-quality convergence additions in v153 remain fail-closed. They
prevent premature authority repair while structural startup proofs are pending,
preserve a healthy legacy capital-refresh owner during publication headroom,
and make a broker object's explicit connectivity state authoritative over stale
manager bookkeeping.
"""
from __future__ import annotations

import logging
import os
import threading
from functools import wraps
from typing import Any

logger = logging.getLogger("nija.kill_switch_coordinator_sync")
_MARKER = "20260814-kill-switch-coordinator-sync-v1"
_QUALITY_MARKER = "20260819-runtime-quality-convergence-v153"
_PATCH_ATTR = "_nija_kill_switch_coordinator_sync_v1"
_RUNTIME_AUTHORITY_GATE_ATTR = "_nija_runtime_quality_v153_structural_gate"
_CONNECTIVITY_PATCH_ATTR = "_nija_runtime_quality_v153_truthful_connectivity"
_LOCK = threading.RLock()


def _publish_coordinator_truth(active: bool, source: str) -> bool:
    """Publish canonical kill-switch truth without changing lifecycle state."""
    try:
        from bot.startup_coordinator import StartupEvent, get_startup_coordinator

        coordinator = get_startup_coordinator()
        with coordinator._lock:  # type: ignore[attr-defined]
            runtime = coordinator._runtime  # type: ignore[attr-defined]
            active = bool(active)
            previous = bool(runtime.kill_switch_active)
            if previous == active:
                return True

            runtime.kill_switch_active = active
            runtime.global_epoch += 1
            coordinator._revoke_activation_commit_locked()  # type: ignore[attr-defined]
            runtime._last_reconcile_inputs = None
            coordinator._publish_locked(  # type: ignore[attr-defined]
                StartupEvent.KILL_SWITCH_CHANGED,
                {
                    "active": active,
                    "source": str(source or "canonical_kill_switch"),
                    "global_epoch": runtime.global_epoch,
                    "marker": _MARKER,
                },
            )

        logger.critical(
            "KILL_SWITCH_COORDINATOR_SYNC marker=%s active=%s source=%s global_epoch=%s",
            _MARKER,
            str(active).lower(),
            source,
            runtime.global_epoch,
        )
        return True
    except Exception as exc:
        logger.exception(
            "KILL_SWITCH_COORDINATOR_SYNC_FAILED marker=%s source=%s error=%s",
            _MARKER,
            source,
            exc,
        )
        return False


def _effective_active(instance: Any) -> bool:
    """Fail closed when either in-memory state or the file marker is active."""
    try:
        return bool(
            getattr(instance, "_is_active", False)
            or os.path.exists(str(getattr(instance, "_kill_file", "") or ""))
        )
    except Exception:
        return True


def _patch_kill_switch_class(kill_switch_cls: type) -> bool:
    activate_internal = getattr(kill_switch_cls, "_activate_internal", None)
    deactivate = getattr(kill_switch_cls, "deactivate", None)
    is_active = getattr(kill_switch_cls, "is_active", None)
    if not all(callable(item) for item in (activate_internal, deactivate, is_active)):
        return False

    if not getattr(activate_internal, _PATCH_ATTR, False):
        @wraps(activate_internal)
        def activate_internal_sync(self: Any, reason: str, source: str) -> Any:
            result = activate_internal(self, reason, source)
            _publish_coordinator_truth(True, f"activate:{source}")
            return result

        setattr(activate_internal_sync, _PATCH_ATTR, True)
        kill_switch_cls._activate_internal = activate_internal_sync

    if not getattr(deactivate, _PATCH_ATTR, False):
        @wraps(deactivate)
        def deactivate_sync(self: Any, reason: str = "Manual deactivation") -> Any:
            result = deactivate(self, reason)
            _publish_coordinator_truth(_effective_active(self), "deactivate")
            return result

        setattr(deactivate_sync, _PATCH_ATTR, True)
        kill_switch_cls.deactivate = deactivate_sync

    if not getattr(is_active, _PATCH_ATTR, False):
        @wraps(is_active)
        def is_active_sync(self: Any) -> bool:
            result = bool(is_active(self))
            _publish_coordinator_truth(result, "is_active")
            return result

        setattr(is_active_sync, _PATCH_ATTR, True)
        kill_switch_cls.is_active = is_active_sync

    return True


def _structural_readiness_blockers() -> list[str]:
    """Return startup proofs that must be true before authority repair may commit.

    Writer/nonce authority are deliberately excluded: the canonical authority
    repair validates those itself and publishes those two proofs immediately
    before activation. Everything else here is structural runtime readiness and
    must already be true, preventing a repair heartbeat from racing strategy,
    execution-engine, bootstrap, or position-sync publication.
    """
    try:
        try:
            from bot import readiness_table
        except ImportError:
            import readiness_table  # type: ignore[import,no-redef]
        table = dict(readiness_table.snapshot())
    except Exception as exc:
        logger.warning(
            "RUNTIME_AUTHORITY_STRUCTURAL_GATE_UNAVAILABLE marker=%s error=%s:%s trading_fail_closed=true",
            _QUALITY_MARKER,
            type(exc).__name__,
            exc,
        )
        return ["readiness_table_unavailable"]

    required = [
        "broker_connected",
        "balance_hydrated",
        "capital_ready",
        "risk_ready",
        "strategy_ready",
        "execution_ready",
        "bootstrap_ready",
    ]
    if "position_sync_ready" in table:
        required.append("position_sync_ready")
    return [name for name in required if not bool(table.get(name, False))]


def _patch_runtime_authority_structural_gate() -> bool:
    """Defer runtime-authority convergence until structural readiness is complete."""
    try:
        try:
            from bot import runtime_authority_convergence_repair_patch as repair
        except ImportError:
            import runtime_authority_convergence_repair_patch as repair  # type: ignore[import,no-redef]
    except Exception as exc:
        logger.warning(
            "RUNTIME_AUTHORITY_STRUCTURAL_GATE_IMPORT_FAILED marker=%s error=%s:%s trading_fail_closed=true",
            _QUALITY_MARKER,
            type(exc).__name__,
            exc,
        )
        return False

    current = getattr(repair, "converge_runtime_authority", None)
    if not callable(current):
        return False
    if bool(getattr(current, _RUNTIME_AUTHORITY_GATE_ATTR, False)):
        return True

    @wraps(current)
    def converge_runtime_authority_v153(source: str = "manual") -> bool:
        blockers = _structural_readiness_blockers()
        if blockers:
            logger.info(
                "RUNTIME_AUTHORITY_STRUCTURAL_GATE_DEFERRED marker=%s source=%s blockers=%s activation_attempted=false trading_fail_closed=true",
                _QUALITY_MARKER,
                source,
                blockers,
            )
            return False
        return bool(current(source))

    setattr(converge_runtime_authority_v153, _RUNTIME_AUTHORITY_GATE_ATTR, True)
    setattr(converge_runtime_authority_v153, "__wrapped__", current)
    repair.converge_runtime_authority = converge_runtime_authority_v153
    logger.critical(
        "RUNTIME_AUTHORITY_STRUCTURAL_GATE_INSTALLED marker=%s strategy_execution_bootstrap_position_sync_required=true writer_nonce_checks_unchanged=true",
        _QUALITY_MARKER,
    )
    return True


def _install_truthful_connectivity(publication_liveness: Any) -> bool:
    """Make explicit broker connectivity authoritative over stale manager state."""
    current = getattr(publication_liveness, "_canonical_broker_connectivity", None)
    if not callable(current):
        return False
    if bool(getattr(current, _CONNECTIVITY_PATCH_ATTR, False)):
        return True

    def canonical_broker_connectivity_v153() -> tuple[bool, dict[str, Any]]:
        manager = publication_liveness._canonical_manager()
        if manager is None:
            return False, {"reason": "manager_missing", "connected": [], "registered": []}

        platform = getattr(manager, "_platform_brokers", None)
        if not isinstance(platform, dict) or not platform:
            return False, {"reason": "platform_registry_empty", "connected": [], "registered": []}

        registered: list[str] = []
        connected: list[str] = []
        probe = getattr(manager, "is_platform_connected", None)
        state_map = getattr(manager, "_platform_state", {})
        for raw_key, broker in list(platform.items()):
            if broker is None:
                continue
            name = str(getattr(raw_key, "value", raw_key) or "").strip().lower()
            if not name:
                continue
            registered.append(name)

            direct_observed = False
            direct_connected = False
            for attr in ("connected", "is_connected"):
                if not hasattr(broker, attr):
                    continue
                direct_observed = True
                try:
                    value = getattr(broker, attr)
                    direct_connected = bool(value() if callable(value) else value)
                except Exception:
                    direct_connected = False
                break

            # When the canonical broker object exposes connectivity, that truth
            # wins. Manager/state maps are compatibility fallbacks only for
            # adapters that do not expose a direct connectivity surface.
            if direct_observed:
                if direct_connected:
                    connected.append(name)
                continue

            manager_connected = False
            if callable(probe):
                try:
                    manager_connected = bool(probe(raw_key))
                except Exception:
                    manager_connected = False
            state_connected = False
            if isinstance(state_map, dict):
                state = state_map.get(name, state_map.get(raw_key))
                state_value = str(getattr(state, "value", state) or "").strip().lower()
                state_connected = state_value == "connected"
            if manager_connected or state_connected:
                connected.append(name)

        policy = str(os.environ.get("NIJA_SECONDARY_VENUE_POLICY", "optional") or "optional").strip().lower()
        if policy == "global_all_required":
            ready = bool(registered and len(set(connected)) == len(set(registered)))
        else:
            ready = bool(connected)
        return ready, {
            "reason": "ok" if ready else "canonical_platform_connectivity_not_proven",
            "policy": policy,
            "registered": sorted(set(registered)),
            "connected": sorted(set(connected)),
            "direct_connectivity_authoritative": True,
        }

    setattr(canonical_broker_connectivity_v153, _CONNECTIVITY_PATCH_ATTR, True)
    setattr(canonical_broker_connectivity_v153, "__wrapped__", current)
    publication_liveness._canonical_broker_connectivity = canonical_broker_connectivity_v153
    logger.critical(
        "CANONICAL_BROKER_CONNECTIVITY_TRUTH_V153_INSTALLED marker=%s direct_state_authoritative=true stale_manager_override=false",
        _QUALITY_MARKER,
    )
    return True


def _prepare_capital_publication_liveness(publication_liveness: Any) -> bool:
    """Normalize v142 wrapper proof and coordinator rollover semantics.

    ``functools.wraps`` copies ``__name__`` and ownership attributes from the
    wrapped function. The stable identity of the wrapper implementation is the
    underlying code object's ``co_name``. Use that plus the ownership marker so
    copied attributes on unrelated outer wrappers cannot falsely prove the v35
    or v78 layer is still present.

    v153 also preserves a pre-v142/untracked refresh owner while the current
    capital publication is still valid. The underlying v142 liveness function
    already retires that owner once publication truth is no longer current, so
    replacing it merely because refresh headroom opened created unnecessary
    duplicate coordinators and rejected late untagged publications.
    """
    if bool(getattr(publication_liveness, "_nija_startup_chain_prepared", False)):
        return _install_truthful_connectivity(publication_liveness)

    def marker_chain_contains(callable_obj: Any, *, marker: str, expected_name: str = "") -> bool:
        seen: set[int] = set()
        current = callable_obj
        for _ in range(32):
            if not callable(current) or id(current) in seen:
                return False
            seen.add(id(current))
            if bool(getattr(current, marker, False)):
                if not expected_name:
                    return True
                code = getattr(current, "__code__", None)
                if str(getattr(code, "co_name", "") or "") == expected_name:
                    return True
            current = getattr(current, "__wrapped__", None)
        return False

    publication_liveness._chain_contains = marker_chain_contains

    original_inflight = getattr(publication_liveness, "_coordinator_in_flight_v142", None)
    if not callable(original_inflight):
        return False

    @wraps(original_inflight)
    def coordinator_in_flight_with_upgrade_rollover(manager: Any) -> bool:
        coordinator = getattr(manager, "_capital_coordinator", None)
        if coordinator is None or not bool(getattr(coordinator, "_in_flight", False)):
            return False

        tracked = bool(getattr(coordinator, "_nija_v142_flight_generation", 0))
        if not tracked:
            # Preserve the existing owner during freshness headroom. The base
            # v142 probe is already fail-closed and only retires an untracked
            # owner once the immutable publication is no longer current.
            result = bool(original_inflight(manager))
            logger.debug(
                "CAPITAL_PUBLICATION_V153_UNTRACKED_OWNER_PROBE marker=%s in_flight=%s rollover_on_headroom=false",
                _QUALITY_MARKER,
                result,
            )
            return result

        # A tracked v142 owner has a generation before its worker-thread handle
        # is published. Treat that brief pre-start window as live unless it has
        # already exceeded the total runtime deadline. This closes the race where
        # a concurrent v137 probe could otherwise roll over a healthy refresh.
        timed_out = bool(getattr(coordinator, "_nija_v142_flight_timed_out", False))
        age_s = float(publication_liveness._flight_age_s(coordinator))
        limit_s = float(publication_liveness._runtime_pipeline_deadline_seconds())
        worker = getattr(coordinator, "_nija_v142_flight_thread", None)
        alive_fn = getattr(worker, "is_alive", None) if worker is not None else None
        worker_known = worker is not None and callable(alive_fn)
        worker_alive = bool(alive_fn()) if worker_known else False

        if not timed_out and age_s <= limit_s + 1.0:
            if not worker_known or worker_alive:
                return True

        if timed_out:
            reason = "coordinator_timeout_flag"
        elif not worker_known:
            reason = "coordinator_worker_handle_missing_after_deadline"
        elif not worker_alive:
            reason = "coordinator_owner_dead"
        else:
            reason = "coordinator_age_exceeded"

        replacement = publication_liveness._rollover_coordinator(
            manager,
            expected_old=coordinator,
            reason=reason,
        )
        logger.critical(
            "CAPITAL_PUBLICATION_V142_TRACKED_ROLLOVER marker=%s reason=%s age_s=%.1f "
            "limit_s=%.1f worker_known=%s worker_alive=%s old_id=%s new_id=%s "
            "late_publication_fenced=true trading_fail_closed_until_refresh=true",
            _MARKER,
            reason,
            age_s,
            limit_s,
            str(worker_known).lower(),
            str(worker_alive).lower(),
            hex(id(coordinator)),
            hex(id(replacement)) if replacement is not None else "none",
        )
        return bool(replacement is coordinator or replacement is None)

    setattr(coordinator_in_flight_with_upgrade_rollover, "_nija_v142_upgrade_rollover", True)
    publication_liveness._coordinator_in_flight_v142 = coordinator_in_flight_with_upgrade_rollover
    publication_liveness._nija_startup_chain_prepared = True
    return _install_truthful_connectivity(publication_liveness)


def _install_authority_liveness() -> bool:
    """Chain narrow runtime liveness repairs fail-closed."""
    try:
        from bot import runtime_killswitch_authority_liveness_patch as liveness

        installer = getattr(liveness, "install_import_hook", None) or getattr(
            liveness, "install", None
        )
        if not callable(installer) or not bool(installer()):
            return False
    except Exception as exc:
        logger.exception(
            "KILL_SWITCH_AUTHORITY_LIVENESS_CHAIN_FAILED marker=%s error=%s",
            _MARKER,
            exc,
        )
        return False

    try:
        from bot import stalled_writer_capital_freshness_v141_patch as capital_liveness

        installer = getattr(capital_liveness, "install_import_hook", None) or getattr(
            capital_liveness, "install", None
        )
        if not callable(installer) or not bool(installer()):
            return False
    except Exception as exc:
        logger.exception(
            "STALLED_WRITER_CAPITAL_FRESHNESS_CHAIN_FAILED marker=%s error=%s",
            _MARKER,
            exc,
        )
        return False

    try:
        from bot import capital_publication_liveness_v142_patch as publication_liveness

        if not _prepare_capital_publication_liveness(publication_liveness):
            return False
        installer = getattr(publication_liveness, "install_import_hook", None) or getattr(
            publication_liveness, "install", None
        )
        if not callable(installer) or not bool(installer()):
            return False
        # v142 installation can replace its own connectivity function; reassert
        # v153 truth semantics after the installer completes.
        if not _install_truthful_connectivity(publication_liveness):
            return False
    except Exception as exc:
        logger.exception(
            "CAPITAL_PUBLICATION_LIVENESS_CHAIN_FAILED marker=%s error=%s",
            _MARKER,
            exc,
        )
        return False

    try:
        from bot import kill_switch_persistence_provenance_v143_patch as provenance_liveness

        installer = getattr(provenance_liveness, "install_import_hook", None) or getattr(
            provenance_liveness, "install", None
        )
        if not callable(installer) or not bool(installer()):
            return False
    except Exception as exc:
        logger.exception(
            "KILL_SWITCH_PERSISTENCE_PROVENANCE_V143_CHAIN_FAILED marker=%s error=%s",
            _MARKER,
            exc,
        )
        return False

    if not _patch_runtime_authority_structural_gate():
        return False
    return True


def install_import_hook() -> None:
    """Install synchronization and immediately reconcile preexisting state."""
    with _LOCK:
        from bot import kill_switch as kill_switch_module

        kill_switch_cls = getattr(kill_switch_module, "KillSwitch", None)
        if not isinstance(kill_switch_cls, type) or not _patch_kill_switch_class(kill_switch_cls):
            raise RuntimeError("canonical_kill_switch_not_patchable")

        getter = getattr(kill_switch_module, "get_kill_switch", None)
        if not callable(getter):
            raise RuntimeError("canonical_kill_switch_getter_missing")

        instance = getter()
        active = bool(instance.is_active())
        if not _publish_coordinator_truth(active, "install_reconcile"):
            raise RuntimeError("startup_coordinator_sync_failed")
        if not _install_authority_liveness():
            raise RuntimeError("runtime_liveness_guards_not_ready")

        os.environ["NIJA_KILL_SWITCH_COORDINATOR_SYNC_INSTALLED"] = "1"
        os.environ["NIJA_KILL_SWITCH_COORDINATOR_SYNC_READY"] = "1"
        os.environ["NIJA_RUNTIME_QUALITY_CONVERGENCE_V153_READY"] = "1"
        logger.critical(
            "KILL_SWITCH_COORDINATOR_SYNC_INSTALLED marker=%s active=%s auto_clear=false "
            "risk_gates_unchanged=true authority_liveness_chained=true "
            "stalled_writer_capital_freshness_chained=true "
            "capital_publication_liveness_chained=true "
            "kill_switch_persistence_provenance_chained=true "
            "runtime_quality_marker=%s authority_structural_gate=true "
            "truthful_broker_connectivity=true untracked_refresh_owner_preserved=true",
            _MARKER,
            str(active).lower(),
            _QUALITY_MARKER,
        )


def install() -> None:
    install_import_hook()


__all__ = [
    "install",
    "install_import_hook",
    "_patch_kill_switch_class",
    "_publish_coordinator_truth",
    "_prepare_capital_publication_liveness",
    "_install_authority_liveness",
    "_structural_readiness_blockers",
    "_patch_runtime_authority_structural_gate",
    "_install_truthful_connectivity",
]
