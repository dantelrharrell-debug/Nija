"""Pre-core authority heartbeat contract repair v63.

The canonical writer authority intentionally publishes ``NIJA_CORE_THREAD_ALIVE=0``
while the process still owns a healthy writer lease but the real trading core has
not been launched/registered yet.  ``authority_heartbeat._check_authority_once``
previously treated that temporary value as an already-dead core and could enter
lockdown (including a SEAK emergency halt) before ``bot_main`` reached the engine
handoff.

This guard aligns the independent heartbeat with the writer runtime's existing
startup-grace contract.  It suppresses only the pre-core liveness flag while all
of the following remain true:

* the canonical writer singleton exists and still has no core thread;
* core registration has not occurred;
* the scan-start deadline has not expired;
* startup has not completed;
* no terminal startup failure or shutdown request exists.

After any of those conditions change, ``NIJA_CORE_THREAD_ALIVE=0`` is passed to
the original heartbeat unchanged and remains fail-closed.  Redis fencing,
generation, heartbeat-loop, kill-switch, nonce, and execution gates are never
bypassed.
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

LOGGER = logging.getLogger("nija.precore_authority_heartbeat_v63")
MARKER = "20260812-precore-authority-heartbeat-v63"
_LOCK = threading.RLock()
_PATCH_ATTR = "_nija_precore_authority_heartbeat_v63"
_HOOK_FLAG = "_NIJA_PRECORE_AUTHORITY_HEARTBEAT_V63_IMPORT_HOOK"
_MODULE_NAMES = ("bot.authority_heartbeat", "authority_heartbeat")


def _canonical_writer_runtime() -> Any:
    for name in ("bot.entrypoint_writer_authority", "entrypoint_writer_authority"):
        module = sys.modules.get(name)
        if not isinstance(module, ModuleType):
            continue
        getter = getattr(module, "get_entrypoint_writer_authority", None)
        if callable(getter):
            try:
                return getter()
            except Exception:
                return None
    return None


def _precore_grace_active() -> tuple[bool, str]:
    runtime = _canonical_writer_runtime()
    if runtime is None:
        return False, "writer_runtime_unavailable"

    if bool(getattr(runtime, "lost", False)):
        return False, "writer_lost"
    if str(getattr(runtime, "terminal_startup_failure_reason", "") or "").strip():
        return False, "terminal_startup_failure"
    if bool(getattr(runtime, "_scan_deadline_exceeded", False)):
        return False, "scan_deadline_exceeded"

    core = getattr(runtime, "_core_thread", None)
    registered = bool(getattr(runtime, "_core_thread_registered", False))
    if core is not None or registered:
        return False, "core_handoff_started"

    bot_main = sys.modules.get("bot.bot_main") or sys.modules.get("bot_main")
    if isinstance(bot_main, ModuleType):
        shutdown = getattr(bot_main, "_shutdown_event", None)
        if shutdown is not None and callable(getattr(shutdown, "is_set", None)):
            try:
                if shutdown.is_set():
                    return False, "shutdown_requested"
            except Exception:
                return False, "shutdown_state_unavailable"
        if bool(getattr(bot_main, "_startup_complete", False)):
            return False, "startup_complete_without_core"

    return True, "startup_not_registered"


def _patch_authority_heartbeat(module: ModuleType) -> bool:
    current = getattr(module, "_check_authority_once", None)
    if not callable(current):
        return False
    if getattr(current, _PATCH_ATTR, False):
        return True

    @wraps(current)
    def check_authority_once_v63(timeout_s: float):
        raw = str(os.environ.get("NIJA_CORE_THREAD_ALIVE", "") or "").strip().lower()
        if raw and raw not in {"1", "true", "yes", "on", "enabled"}:
            grace, reason = _precore_grace_active()
            if grace:
                previous = os.environ.pop("NIJA_CORE_THREAD_ALIVE", None)
                try:
                    result = current(timeout_s)
                finally:
                    if previous is not None:
                        os.environ["NIJA_CORE_THREAD_ALIVE"] = previous
                LOGGER.info(
                    "PRECORE_AUTHORITY_HEARTBEAT_GRACE marker=%s reason=%s "
                    "core_alive_signal=%s other_authority_gates_unchanged=true",
                    MARKER,
                    reason,
                    raw,
                )
                return result
        return current(timeout_s)

    setattr(check_authority_once_v63, _PATCH_ATTR, True)
    setattr(check_authority_once_v63, "__wrapped__", current)
    module._check_authority_once = check_authority_once_v63
    LOGGER.critical(
        "PRECORE_AUTHORITY_HEARTBEAT_V63_PATCHED marker=%s module=%s "
        "precore_zero_grace=true postcore_fail_closed=true",
        MARKER,
        module.__name__,
    )
    return True


def _patch_loaded() -> bool:
    changed = False
    seen: set[int] = set()
    for name in _MODULE_NAMES:
        module = sys.modules.get(name)
        if isinstance(module, ModuleType) and id(module) not in seen:
            seen.add(id(module))
            changed = _patch_authority_heartbeat(module) or changed
    return changed


def install_import_hook() -> bool:
    with _LOCK:
        _patch_loaded()
        if not getattr(builtins, _HOOK_FLAG, False):
            original_import = builtins.__import__

            @wraps(original_import)
            def importing(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
                result = original_import(name, globals, locals, fromlist, level)
                if "authority_heartbeat" in str(name):
                    _patch_loaded()
                return result

            builtins.__import__ = importing
            setattr(builtins, _HOOK_FLAG, True)

        os.environ["NIJA_PRECORE_AUTHORITY_HEARTBEAT_V63_READY"] = "1"
        LOGGER.critical(
            "PRECORE_AUTHORITY_HEARTBEAT_V63_INSTALLED marker=%s "
            "precore_grace_only=true authority_bypass=false",
            MARKER,
        )
        return True


def install() -> bool:
    return install_import_hook()


__all__ = ["MARKER", "install", "install_import_hook", "_precore_grace_active"]
