"""Bind startup position synchronization into canonical dispatch authority.

v95 bounded broker position snapshots and blocked fresh activation while any
connected broker lacked an authoritative startup snapshot. Production evidence
then showed a pre-existing StartupCoordinator dispatch commit could remain live
because position-sync truth was not part of the canonical readiness table.

v96 publishes a dynamic ``position_sync_ready`` readiness key. The coordinator
already treats every readiness-table entry as part of its execution proof, so a
false value immediately makes execution non-permitted; a true-to-false
regression also advances the global epoch and revokes an existing activation
commit through the canonical coordinator path.

v195 makes the installer replay-idempotent.  The first process install still
publishes an explicit fail-closed position-sync key before activation can consume
old state, but later installer replays no longer overwrite already-proven live
position-sync/reconciliation truth with an artificial ``manager=None`` result.
Real broker-set or fetch-proof regressions still publish false through the normal
runtime paths.

No writer, nonce, capital, risk, strategy, kill-switch, or execution authority is
synthesized here. Readiness becomes true only when at least one broker is
connected and every currently connected platform/user broker has completed an
authoritative startup position snapshot.
"""
from __future__ import annotations

import builtins
import logging
import os
import sys
import threading
from functools import wraps
from types import ModuleType
from typing import Any

LOGGER = logging.getLogger("nija.position_sync_dispatch_authority_v96")
MARKER = "20260814-position-sync-dispatch-authority-v96"
V195_MARKER = "20260823-position-sync-installer-idempotence-v195"
READINESS_KEY = "position_sync_ready"
_LOCK = threading.RLock()
_HOOK_FLAG = "_NIJA_POSITION_SYNC_DISPATCH_AUTHORITY_V96_IMPORT_HOOK"
_INITIAL_FAIL_CLOSED_FLAG = "_NIJA_POSITION_SYNC_DISPATCH_AUTHORITY_V96_INITIAL_FAIL_CLOSED"
_MABM_ATTR = "_nija_position_sync_dispatch_authority_v96"
_SYNC_ATTR = "_nija_position_sync_dispatch_authority_v96"


def _readiness_module() -> ModuleType:
    try:
        import bot.readiness_table as readiness_table
    except ImportError:
        import readiness_table  # type: ignore[import]
    return readiness_table


def _v95_module() -> ModuleType:
    try:
        import bot.position_sync_core_handoff_v95_patch as v95
    except ImportError:
        import position_sync_core_handoff_v95_patch as v95  # type: ignore[import]
    return v95


def _manager_from_strategy(strategy: Any) -> Any:
    manager = getattr(strategy, "multi_account_manager", None)
    if manager is not None:
        return manager
    try:
        return _v95_module()._canonical_manager()
    except Exception:
        return None


def publish_position_sync_readiness(manager: Any, *, source: str) -> tuple[bool, list[str], dict[str, bool]]:
    """Publish current position-sync truth into canonical readiness authority."""
    ready = False
    pending: list[str] = []
    status: dict[str, bool] = {}
    if manager is not None:
        try:
            raw_ready, pending, status = _v95_module().position_sync_status(manager)
            # Never treat an empty connected-broker set as dispatch-ready.
            ready = bool(status) and bool(raw_ready)
        except Exception as exc:
            LOGGER.warning(
                "POSITION_SYNC_V96_STATUS_ERROR marker=%s source=%s error=%s:%s fail_closed=true",
                MARKER,
                source,
                type(exc).__name__,
                exc,
            )

    readiness = _readiness_module()
    readiness.set_ready(READINESS_KEY, bool(ready), allow_regression=True)
    os.environ["NIJA_POSITION_SYNC_ACTIVATION_READY"] = "1" if ready else "0"
    os.environ["NIJA_POSITION_SYNC_DISPATCH_READY"] = "1" if ready else "0"

    log = LOGGER.critical if not ready else LOGGER.info
    log(
        "POSITION_SYNC_V96_READINESS marker=%s source=%s ready=%s pending=%s status=%s "
        "canonical_readiness=true stale_commit_revocation=true",
        MARKER,
        source,
        str(bool(ready)).lower(),
        pending,
        status,
    )
    return bool(ready), pending, status


def _patch_mabm(module: ModuleType) -> bool:
    cls = getattr(module, "MultiAccountBrokerManager", None)
    if not isinstance(cls, type):
        return False
    current = getattr(cls, "refresh_capital_authority", None)
    if not callable(current):
        return False
    if getattr(current, _MABM_ATTR, False):
        return True

    @wraps(current)
    def refresh_capital_authority_v96(self: Any, *args: Any, **kwargs: Any):
        result = current(self, *args, **kwargs)
        publish_position_sync_readiness(self, source="refresh_capital_authority")
        return result

    setattr(refresh_capital_authority_v96, _MABM_ATTR, True)
    setattr(refresh_capital_authority_v96, "__wrapped__", current)
    cls.refresh_capital_authority = refresh_capital_authority_v96
    LOGGER.critical(
        "POSITION_SYNC_V96_MABM_PATCHED marker=%s canonical_readiness_key=%s",
        MARKER,
        READINESS_KEY,
    )
    return True


def _patch_startup_sync(module: ModuleType) -> bool:
    current = getattr(module, "sync_exchange_positions_on_startup", None)
    if not callable(current):
        return False
    if getattr(current, _SYNC_ATTR, False):
        return True

    @wraps(current)
    def sync_exchange_positions_on_startup_v96(strategy: Any, *args: Any, **kwargs: Any):
        result = current(strategy, *args, **kwargs)
        manager = _manager_from_strategy(strategy)
        publish_position_sync_readiness(manager, source="startup_position_sync_complete")
        return result

    setattr(sync_exchange_positions_on_startup_v96, _SYNC_ATTR, True)
    setattr(sync_exchange_positions_on_startup_v96, "__wrapped__", current)
    module.sync_exchange_positions_on_startup = sync_exchange_positions_on_startup_v96
    LOGGER.critical(
        "POSITION_SYNC_V96_STARTUP_SYNC_PATCHED marker=%s canonical_readiness_key=%s",
        MARKER,
        READINESS_KEY,
    )
    return True


def _patch_loaded() -> bool:
    changed = False
    seen: set[int] = set()
    for name in ("bot.multi_account_broker_manager", "multi_account_broker_manager"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType) and id(module) not in seen:
            seen.add(id(module))
            changed = _patch_mabm(module) or changed
    for name in ("bot.startup_position_sync", "startup_position_sync"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType) and id(module) not in seen:
            seen.add(id(module))
            changed = _patch_startup_sync(module) or changed
    return changed


def install_import_hook() -> bool:
    with _LOCK:
        # Establish the fail-closed key exactly once per Python process before
        # activation can consume an old coordinator commit.  Installer replay is
        # common in the canonical release chain; replay must not revoke a proven
        # live state merely because the installer itself has no manager argument.
        initial_fail_closed = not bool(getattr(builtins, _INITIAL_FAIL_CLOSED_FLAG, False))
        if initial_fail_closed:
            publish_position_sync_readiness(None, source="install_fail_closed")
            setattr(builtins, _INITIAL_FAIL_CLOSED_FLAG, True)
        else:
            LOGGER.info(
                "POSITION_SYNC_V195_INSTALL_REPLAY_PRESERVED marker=%s "
                "initial_fail_closed_replayed=false proven_runtime_state_unchanged=true "
                "real_regressions_still_fail_closed=true",
                V195_MARKER,
            )

        _patch_loaded()
        if not getattr(builtins, _HOOK_FLAG, False):
            original_import = builtins.__import__

            @wraps(original_import)
            def importing(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
                result = original_import(name, globals, locals, fromlist, level)
                text = str(name or "")
                if "multi_account_broker_manager" in text or "startup_position_sync" in text:
                    _patch_loaded()
                return result

            builtins.__import__ = importing
            setattr(builtins, _HOOK_FLAG, True)

        os.environ["NIJA_POSITION_SYNC_DISPATCH_AUTHORITY_V96_INSTALLED"] = "1"
        os.environ["NIJA_POSITION_SYNC_INSTALLER_IDEMPOTENCE_V195_READY"] = "1"
        LOGGER.critical(
            "POSITION_SYNC_DISPATCH_AUTHORITY_V96_INSTALLED marker=%s readiness_key=%s "
            "fail_closed=true stale_commit_revocation=true installer_replay_idempotent_v195=true "
            "safety_gates_unchanged=true",
            MARKER,
            READINESS_KEY,
        )
        return True


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER",
    "V195_MARKER",
    "READINESS_KEY",
    "install",
    "install_import_hook",
    "publish_position_sync_readiness",
    "_patch_mabm",
    "_patch_startup_sync",
]
