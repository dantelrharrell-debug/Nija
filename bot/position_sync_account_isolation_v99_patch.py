"""Keep platform startup readiness independent from per-user position sync.

Production deployment ed2001a7 on 2026-08-15 showed all three platform venues
fully synchronized while a connected Kraken user account repeatedly exceeded the
bounded position-fetch timeout. v95/v96 correctly failed closed, but their
all-connected-brokers rule allowed one user account to hold the entire platform
in LIVE_PENDING_CONFIRMATION.

NIJA's account architecture is explicitly isolated: platform trading must not be
blocked by a user account failure, while that user must remain fail closed until
its own positions are authoritative. v99 enforces that split:

* global activation/readiness consumes only connected platform-broker snapshots;
* the original all-account status function remains available for diagnostics;
* CopyTradeEngine order submission is blocked for an unsynchronized user broker;
* the recurring runtime reconciler remains unchanged and can later promote the
  user broker after a real position snapshot succeeds.

No position-sync success, broker connectivity, execution authority, risk state,
writer/nonce authority, or kill-switch state is fabricated.
"""
from __future__ import annotations

import builtins
import logging
import os
import sys
import threading
from functools import wraps
from types import ModuleType
from typing import Any, Callable

LOGGER = logging.getLogger("nija.position_sync_account_isolation_v99")
MARKER = "20260815-position-sync-account-isolation-v99"
_LOCK = threading.RLock()
_HOOK_FLAG = "_NIJA_POSITION_SYNC_ACCOUNT_ISOLATION_V99_IMPORT_HOOK"
_COPY_ATTR = "_nija_position_sync_account_isolation_v99"
_ORIGINAL_STATUS: Callable[[Any], tuple[bool, list[str], dict[str, bool]]] | None = None
_LAST_USER_SIGNATURE = ""
_IMPORT_LOCAL = threading.local()


def _v95_module() -> ModuleType:
    try:
        import bot.position_sync_core_handoff_v95_patch as v95
    except ImportError:
        import position_sync_core_handoff_v95_patch as v95  # type: ignore[import]
    return v95


def _all_account_status(manager: Any) -> tuple[bool, list[str], dict[str, bool]]:
    global _ORIGINAL_STATUS
    v95 = _v95_module()
    original = _ORIGINAL_STATUS
    if original is None:
        candidate = getattr(v95, "position_sync_status", None)
        if not callable(candidate):
            return False, ["position_sync_status_unavailable"], {}
        original = candidate
        _ORIGINAL_STATUS = original
    return original(manager)


def _platform_position_sync_status(manager: Any) -> tuple[bool, list[str], dict[str, bool]]:
    """Return fail-closed global readiness for connected platform brokers only."""
    v95 = _v95_module()
    try:
        brokers = dict(v95._connected_brokers(manager) or {})
    except Exception:
        brokers = {}
    platform = {
        name: broker
        for name, broker in brokers.items()
        if str(name).startswith("platform:")
    }
    status = {
        name: bool(getattr(broker, "_startup_position_sync_adopted", False))
        for name, broker in platform.items()
    }
    pending = sorted(name for name, synced in status.items() if not synced)
    return bool(status) and not pending, pending, status


def _publish_user_diagnostics(manager: Any) -> None:
    global _LAST_USER_SIGNATURE
    try:
        _ready, _pending, status = _all_account_status(manager)
    except Exception:
        return
    user_status = {
        name: synced for name, synced in status.items()
        if str(name).startswith("user:")
    }
    pending_users = sorted(name for name, synced in user_status.items() if not synced)
    signature = repr((pending_users, sorted(user_status.items())))
    os.environ["NIJA_USER_POSITION_SYNC_PENDING"] = ",".join(pending_users)
    os.environ["NIJA_USER_POSITION_SYNC_READY"] = "1" if user_status and not pending_users else "0"
    if signature == _LAST_USER_SIGNATURE:
        return
    _LAST_USER_SIGNATURE = signature
    log = LOGGER.warning if pending_users else LOGGER.info
    log(
        "USER_POSITION_SYNC_V99_STATUS marker=%s pending=%s status=%s "
        "global_activation_isolated=true user_execution_fail_closed=true",
        MARKER,
        pending_users,
        user_status,
    )


def position_sync_status_v99(manager: Any) -> tuple[bool, list[str], dict[str, bool]]:
    ready, pending, status = _platform_position_sync_status(manager)
    _publish_user_diagnostics(manager)
    return ready, pending, status


def _patch_v95() -> bool:
    global _ORIGINAL_STATUS
    v95 = _v95_module()
    current = getattr(v95, "position_sync_status", None)
    if not callable(current):
        return False
    if current is position_sync_status_v99:
        return True
    if _ORIGINAL_STATUS is None:
        _ORIGINAL_STATUS = current
    setattr(v95, "all_account_position_sync_status", _ORIGINAL_STATUS)
    setattr(v95, "platform_position_sync_status", _platform_position_sync_status)
    setattr(v95, "position_sync_status", position_sync_status_v99)
    LOGGER.critical(
        "POSITION_SYNC_V99_GLOBAL_SCOPE_PATCHED marker=%s scope=platform_only "
        "all_account_diagnostics_preserved=true user_fail_closed=true",
        MARKER,
    )
    return True


def _guard_submitter(current: Callable[..., Any]) -> Callable[..., Any]:
    if getattr(current, _COPY_ATTR, False):
        return current

    @wraps(current)
    def submit_guarded(*args: Any, **kwargs: Any):
        broker = kwargs.get("broker")
        if broker is None and args:
            broker = args[0]
        if broker is None or not bool(getattr(broker, "_startup_position_sync_adopted", False)):
            LOGGER.warning(
                "USER_COPY_TRADE_POSITION_SYNC_BLOCK marker=%s broker=%s "
                "position_sync_ready=false broker_io=false",
                MARKER,
                type(broker).__name__ if broker is not None else "none",
            )
            return {
                "status": "skipped",
                "error": "user position sync incomplete; copy trade remains fail closed",
                "position_sync_ready": False,
            }
        return current(*args, **kwargs)

    setattr(submit_guarded, _COPY_ATTR, True)
    setattr(submit_guarded, "__wrapped__", current)
    return submit_guarded


def _patch_copy_trade_engine(module: ModuleType) -> bool:
    current = getattr(module, "submit_market_order_via_pipeline", None)
    if current is None:
        return True
    if not callable(current):
        return False
    if getattr(current, _COPY_ATTR, False):
        return True
    module.submit_market_order_via_pipeline = _guard_submitter(current)
    LOGGER.critical(
        "POSITION_SYNC_V99_COPY_TRADE_GUARD_PATCHED marker=%s "
        "user_position_sync_required=true direct_fallback=false",
        MARKER,
    )
    return True


def _patch_loaded() -> bool:
    ready = _patch_v95()
    seen: set[int] = set()
    for name in ("bot.copy_trade_engine", "copy_trade_engine"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType) and id(module) not in seen:
            seen.add(id(module))
            ready = _patch_copy_trade_engine(module) and ready
    return ready


def install_import_hook() -> bool:
    with _LOCK:
        if not _patch_loaded():
            return False
        if not getattr(builtins, _HOOK_FLAG, False):
            original_import = builtins.__import__

            @wraps(original_import)
            def importing(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
                result = original_import(name, globals, locals, fromlist, level)
                text = str(name or "")
                if "copy_trade_engine" in text or "position_sync_core_handoff_v95_patch" in text:
                    depth = int(getattr(_IMPORT_LOCAL, "patch_depth", 0) or 0)
                    if depth == 0:
                        _IMPORT_LOCAL.patch_depth = 1
                        try:
                            _patch_loaded()
                        finally:
                            _IMPORT_LOCAL.patch_depth = 0
                    else:
                        LOGGER.debug(
                            "POSITION_SYNC_V99_IMPORT_REENTRY_SUPPRESSED marker=%s name=%s depth=%d",
                            MARKER,
                            text,
                            depth,
                        )
                return result

            builtins.__import__ = importing
            setattr(builtins, _HOOK_FLAG, True)

        os.environ["NIJA_POSITION_SYNC_ACCOUNT_ISOLATION_V99_INSTALLED"] = "1"
        LOGGER.critical(
            "POSITION_SYNC_ACCOUNT_ISOLATION_V99_INSTALLED marker=%s "
            "global_scope=platform user_scope=account_local import_reentry_guard=true safety_gates_unchanged=true",
            MARKER,
        )
        return True


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "position_sync_status_v99",
    "_all_account_status",
    "_platform_position_sync_status",
    "_guard_submitter",
    "_patch_copy_trade_engine",
]
