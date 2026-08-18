"""Keep StartupCoordinator kill-switch truth aligned with the canonical KillSwitch.

The canonical kill switch is the safety authority. This patch mirrors its
active/inactive state into StartupCoordinator without clearing the stop,
changing risk gates, or forcing a coordinator lifecycle state. A state change
invalidates any prior activation commit and advances the global epoch so a
fresh activation proof is required after deactivation.
"""
from __future__ import annotations

import logging
import os
import threading
from functools import wraps
from typing import Any

logger = logging.getLogger("nija.kill_switch_coordinator_sync")
_MARKER = "20260814-kill-switch-coordinator-sync-v1"
_PATCH_ATTR = "_nija_kill_switch_coordinator_sync_v1"
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


def _prepare_capital_publication_liveness(publication_liveness: Any) -> bool:
    """Normalize v142 wrapper proof and coordinator rollover semantics.

    ``functools.wraps`` copies ``__name__`` and ownership attributes from the
    wrapped function. The stable identity of the wrapper implementation is the
    underlying code object's ``co_name``. Use that plus the ownership marker so
    copied attributes on unrelated outer wrappers cannot falsely prove the v35
    or v78 layer is still present.

    The liveness probe also handles two transition states safely:

    * a coordinator that was already in-flight before v142 was installed is
      replaced as soon as v137 enters refresh headroom; and
    * a newly tracked v142 refresh is never considered dead during the tiny
      interval between publishing ``_in_flight``/generation state and storing
      the worker-thread handle.
    """
    if bool(getattr(publication_liveness, "_nija_startup_chain_prepared", False)):
        return True

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
            try:
                from bot import capital_publication_deadline_v137_patch as v137

                authority = publication_liveness._authority()
                due, meta = v137._publication_refresh_due(authority, manager)
            except Exception as exc:
                logger.warning(
                    "CAPITAL_PUBLICATION_V142_UPGRADE_PROBE_FAILED marker=%s err=%s:%s "
                    "existing_owner_preserved=true trading_fail_closed=true",
                    _MARKER,
                    type(exc).__name__,
                    exc,
                )
                return True

            if not due:
                return True

            replacement = publication_liveness._rollover_coordinator(
                manager,
                expected_old=coordinator,
                reason="untracked_inflight_refresh_due:" + str(meta.get("due_reason") or "due"),
            )
            logger.critical(
                "CAPITAL_PUBLICATION_V142_UPGRADE_ROLLOVER marker=%s due_reason=%s "
                "remaining_s=%s old_id=%s new_id=%s pre_expiry=%s "
                "publication_expiry_extended=false trading_fail_closed_until_refresh=true",
                _MARKER,
                meta.get("due_reason"),
                meta.get("remaining_s"),
                hex(id(coordinator)),
                hex(id(replacement)) if replacement is not None else "none",
                str(float(meta.get("remaining_s", 0.0) or 0.0) > 0.0).lower(),
            )
            return bool(replacement is coordinator or replacement is None)

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
    return True


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
    except Exception as exc:
        logger.exception(
            "CAPITAL_PUBLICATION_LIVENESS_CHAIN_FAILED marker=%s error=%s",
            _MARKER,
            exc,
        )
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
        logger.critical(
            "KILL_SWITCH_COORDINATOR_SYNC_INSTALLED marker=%s active=%s auto_clear=false "
            "risk_gates_unchanged=true authority_liveness_chained=true "
            "stalled_writer_capital_freshness_chained=true "
            "capital_publication_liveness_chained=true",
            _MARKER,
            str(active).lower(),
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
]
