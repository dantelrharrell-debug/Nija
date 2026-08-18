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
            "stalled_writer_capital_freshness_chained=true",
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
    "_install_authority_liveness",
]
