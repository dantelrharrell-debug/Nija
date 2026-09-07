"""Keep diagnostic authority-status updates from revoking a valid LIVE commit.

Production on 2026-09-07 exposed a narrow coordinator churn loop:

* ``TradingStateMachine`` published ``authority_ready=True`` with status metadata
  such as ``{"current_state": "LIVE_ACTIVE"}``.
* ``authority_heartbeat`` published the same authority truth with status metadata
  such as ``{"source": "authority_heartbeat"}``.
* ``StartupCoordinator.record_authority`` treated any status-dict difference as
  an authority change, incremented ``global_epoch`` and revoked the canonical
  dispatch commit even though authority never became false.
* v92 then correctly rebuilt the commit, producing repeated
  ``commit_version=0 -> positive`` oscillation while the runtime stayed
  ``LIVE_ACTIVE``.

v382 makes the authority epoch edge-triggered on the canonical boolean authority
truth. Diagnostic status changes still update ``authority_version``, publish an
``AUTHORITY_REFRESHED`` event, and remain observable, but they do not invalidate
``global_epoch`` or the dispatch commit while ``ready`` is unchanged.

Safety contract:
- an actual ``ready=True -> False`` or ``False -> True`` transition still advances
  ``global_epoch`` and revokes the prior activation commit exactly as before;
- kill switch, nonce, dispatch-health, capital, readiness, execution-proof and
  risk gates are untouched;
- no readiness value, execution permission, activation state, or trade is forced.
"""
from __future__ import annotations

import builtins
import importlib
import logging
import os
import sys
import threading
from functools import wraps
from types import ModuleType
from typing import Any, Optional

LOGGER = logging.getLogger("nija.authority_status_epoch_stability_v382")
MARKER = "20260907-authority-status-epoch-stability-v382"
_FLAG = "NIJA_AUTHORITY_STATUS_EPOCH_STABILITY_V382_READY"
_PATCH_ATTR = "_nija_authority_status_epoch_stability_v382"
_HOOK_FLAG = "_NIJA_AUTHORITY_STATUS_EPOCH_STABILITY_V382_IMPORT_HOOK"
_LOCK = threading.RLock()


def _patch_startup_coordinator(module: ModuleType | Any | None = None) -> bool:
    if module is None:
        try:
            module = importlib.import_module("bot.startup_coordinator")
        except Exception:
            return False

    cls = getattr(module, "StartupCoordinator", None)
    startup_event = getattr(module, "StartupEvent", None)
    if not isinstance(cls, type) or startup_event is None:
        return False

    current = getattr(cls, "record_authority", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    original = current

    @wraps(original)
    def record_authority_v382(
        self: Any,
        *,
        ready: bool,
        status: Optional[dict[str, Any]] = None,
    ) -> int:
        normalized_ready = bool(ready)
        normalized_status = dict(status or {})

        with self._lock:
            runtime = self._runtime
            ready_changed = bool(runtime.authority_ready) != normalized_ready
            status_changed = dict(runtime.authority_status or {}) != normalized_status

            # authority_version remains an observability/version counter for both
            # semantic authority changes and metadata refreshes.
            if ready_changed or status_changed:
                runtime.authority_version += 1

            # global_epoch is a safety epoch. Only canonical authority truth may
            # invalidate it; source/current_state/timestamp metadata must not.
            if ready_changed and self._reconcile_permitted_locked():
                runtime.global_epoch += 1
                self._revoke_activation_commit_locked()

            runtime.authority_ready = normalized_ready
            runtime.authority_status = normalized_status
            event_version = self._publish_locked(
                startup_event.AUTHORITY_REFRESHED,
                {
                    "ready": runtime.authority_ready,
                    "authority_version": runtime.authority_version,
                    "global_epoch": runtime.global_epoch,
                },
            )

            if status_changed and not ready_changed:
                LOGGER.info(
                    "AUTHORITY_STATUS_METADATA_STABLE_V382 marker=%s ready=%s "
                    "authority_version=%s global_epoch=%s commit_version=%s "
                    "status_keys=%s commit_preserved=true safety_gates_preserved=true",
                    MARKER,
                    normalized_ready,
                    runtime.authority_version,
                    runtime.global_epoch,
                    runtime.last_committed_snapshot_version,
                    sorted(normalized_status.keys()),
                )
            elif ready_changed:
                LOGGER.critical(
                    "AUTHORITY_TRUTH_EDGE_V382 marker=%s ready=%s "
                    "authority_version=%s global_epoch=%s commit_version=%s "
                    "canonical_epoch_invalidated=true safety_gates_preserved=true",
                    MARKER,
                    normalized_ready,
                    runtime.authority_version,
                    runtime.global_epoch,
                    runtime.last_committed_snapshot_version,
                )

            return event_version

    setattr(record_authority_v382, _PATCH_ATTR, True)
    setattr(record_authority_v382, "__wrapped__", original)
    cls.record_authority = record_authority_v382
    LOGGER.critical(
        "AUTHORITY_STATUS_EPOCH_STABILITY_V382_PATCHED marker=%s "
        "status_metadata_noninvalidating=true authority_truth_edge_invalidating=true "
        "forced_activation=false safety_gates_bypassed=false",
        MARKER,
    )
    return True


def _patch_loaded() -> bool:
    changed = False
    seen: set[int] = set()
    for name in ("bot.startup_coordinator", "startup_coordinator"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType) and id(module) not in seen:
            seen.add(id(module))
            changed = _patch_startup_coordinator(module) or changed
    return changed


def install_import_hook() -> bool:
    with _LOCK:
        _patch_loaded()
        if not bool(getattr(builtins, _HOOK_FLAG, False)):
            original_import = builtins.__import__

            @wraps(original_import)
            def importing(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
                result = original_import(name, globals, locals, fromlist, level)
                if "startup_coordinator" in str(name or ""):
                    _patch_loaded()
                return result

            builtins.__import__ = importing
            setattr(builtins, _HOOK_FLAG, True)

        os.environ[_FLAG] = "1"
        LOGGER.critical(
            "AUTHORITY_STATUS_EPOCH_STABILITY_V382_READY marker=%s "
            "authority_status_observable=true authority_ready_canonical=true "
            "commit_churn_removed=true forced_trade=false forced_activation=false "
            "safety_gates_bypassed=false",
            MARKER,
        )
        return True


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "_patch_startup_coordinator",
]
