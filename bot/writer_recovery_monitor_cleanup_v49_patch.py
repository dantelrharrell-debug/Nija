"""NIJA writer recovery monitor cleanup v49.

During v39 fresh-epoch writer recovery each successful Redis acquisition restarts
AuthorityHeartbeatMonitor before synchronous distributed-authority verification.
If that verification fails, v39 releases the attempted writer epoch and retries,
but the newly restarted monitor is left running. That orphan monitor can reach
its independent failure threshold and force an authority lockdown while the
bounded writer re-election loop is still legitimately retrying.

v49 does not weaken any authority check. It only stops the just-restarted
heartbeat monitor when v39's existing synchronous authority verification returns
False, before v39 releases that failed recovery attempt. Successful verification
leaves the monitor untouched.
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
from typing import Any

LOGGER = logging.getLogger("nija.writer_recovery_monitor_cleanup_v49")
MARKER = "20260808-writer-recovery-monitor-cleanup-v49"

_LOCK = threading.RLock()
_PATCH_ATTR = "_nija_writer_recovery_monitor_cleanup_v49"
_INSTALL_FLAG = "_NIJA_WRITER_RECOVERY_MONITOR_CLEANUP_V49_IMPORT_HOOK"
_IMPORTLIB_FLAG = "_NIJA_WRITER_RECOVERY_MONITOR_CLEANUP_V49_IMPORTLIB_HOOK"
_V39_TARGETS = {
    "nija_production_readiness_v39_prebot",
    "bot.production_readiness_v39_patch",
    "production_readiness_v39_patch",
}
_BOT_MAIN_TARGETS = ("bot.bot_main", "bot_main")


def _stop_recovery_monitor(reason: str) -> bool:
    """Stop only the monitor currently published by bot_main, if any."""
    stopped = False
    seen: set[int] = set()
    for name in _BOT_MAIN_TARGETS:
        module = sys.modules.get(name)
        if not isinstance(module, ModuleType) or id(module) in seen:
            continue
        seen.add(id(module))
        monitor = getattr(module, "_authority_heartbeat_monitor", None)
        if monitor is None:
            continue
        stop = getattr(monitor, "stop", None)
        if not callable(stop):
            continue
        try:
            stop()
            stopped = True
            if getattr(module, "_authority_heartbeat_monitor", None) is monitor:
                setattr(module, "_authority_heartbeat_monitor", None)
            LOGGER.warning(
                "WRITER_RECOVERY_V49_MONITOR_STOPPED marker=%s module=%s reason=%s",
                MARKER,
                name,
                reason,
            )
        except Exception as exc:
            LOGGER.error(
                "WRITER_RECOVERY_V49_MONITOR_STOP_FAILED marker=%s module=%s reason=%s err=%s:%s",
                MARKER,
                name,
                reason,
                type(exc).__name__,
                exc,
            )
    return stopped


def _patch_v39(module: ModuleType) -> bool:
    current = getattr(module, "_assert_writer_authority", None)
    if not callable(current):
        return False
    if getattr(current, _PATCH_ATTR, False):
        return True

    original = current

    @wraps(original)
    def _assert_writer_authority() -> bool:
        try:
            ok = bool(original())
        except Exception as exc:
            os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] = "0"
            os.environ["NIJA_EXECUTION_ACTIVE"] = "false"
            _stop_recovery_monitor(f"authority_verify_exception:{type(exc).__name__}")
            raise

        if ok:
            return True

        os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] = "0"
        os.environ["NIJA_EXECUTION_ACTIVE"] = "false"
        _stop_recovery_monitor("post_acquire_authority_verify_failed")
        LOGGER.critical(
            "WRITER_RECOVERY_V49_VERIFY_FAILED_CLEAN marker=%s action=v39_release_then_retry fail_closed=true",
            MARKER,
        )
        return False

    setattr(_assert_writer_authority, _PATCH_ATTR, True)
    setattr(_assert_writer_authority, "__wrapped__", original)
    module._assert_writer_authority = _assert_writer_authority
    os.environ["NIJA_WRITER_RECOVERY_MONITOR_CLEANUP_V49_PATCHED"] = "1"
    LOGGER.critical(
        "WRITER_RECOVERY_MONITOR_CLEANUP_V49_PATCHED marker=%s module=%s authority_checks_unchanged=true",
        MARKER,
        module.__name__,
    )
    return True


def _patch_loaded() -> bool:
    patched = False
    seen: set[int] = set()
    for name in _V39_TARGETS:
        module = sys.modules.get(name)
        if not isinstance(module, ModuleType) or id(module) in seen:
            continue
        seen.add(id(module))
        patched = _patch_v39(module) or patched
    return patched


def install_import_hook() -> bool:
    with _LOCK:
        _patch_loaded()
        if not getattr(builtins, _INSTALL_FLAG, False):
            original_import = builtins.__import__

            @wraps(original_import)
            def importing(name: str, globals: Any = None, locals: Any = None, fromlist: Any = (), level: int = 0):
                result = original_import(name, globals, locals, fromlist, level)
                if str(name or "") in _V39_TARGETS:
                    _patch_loaded()
                return result

            builtins.__import__ = importing
            setattr(builtins, _INSTALL_FLAG, True)

        if not getattr(importlib, _IMPORTLIB_FLAG, False):
            original_import_module = importlib.import_module

            @wraps(original_import_module)
            def import_module(name: str, package: str | None = None):
                result = original_import_module(name, package)
                if str(name or "") in _V39_TARGETS:
                    _patch_loaded()
                return result

            importlib.import_module = import_module  # type: ignore[assignment]
            setattr(importlib, _IMPORTLIB_FLAG, True)

        os.environ["NIJA_WRITER_RECOVERY_MONITOR_CLEANUP_V49_INSTALLED"] = "1"
        LOGGER.critical(
            "WRITER_RECOVERY_MONITOR_CLEANUP_V49_INSTALLED marker=%s fail_closed=true recovery_criteria_unchanged=true",
            MARKER,
        )
        return True


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "_patch_v39",
    "_stop_recovery_monitor",
]
