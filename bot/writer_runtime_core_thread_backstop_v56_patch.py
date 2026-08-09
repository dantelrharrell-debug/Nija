"""Writer runtime core-thread observer backstop v56.

Production on the v55 build exposed a remaining observer split: the canonical
EntrypointWriterAuthority had a live core thread registered on ``runtime._core_thread``
while the v54 lifecycle supervisor only inspected ``bot_main._core_loop_thread``.
If those references diverge, v54 can skip its process-lifetime writer proof even
while the core scan thread is alive. That leaves a fail-closed but half-live
process repeatedly reporting stale writer/scan deadlines instead of entering the
existing bounded recovery or normal-shutdown path.

v56 does not acquire, renew, extend, delete, steal, or fabricate writer authority.
It only broadens v54's read-only core-thread liveness observer so either canonical
reference counts as a live core thread. v54 remains responsible for exact v45
Redis ownership proof, the v39 recovery window, fail-closed execution state, and
normal shutdown when authority cannot be proven.
"""
from __future__ import annotations

import importlib
import logging
import os
import sys
import threading
from types import ModuleType
from typing import Any

LOGGER = logging.getLogger("nija.writer_runtime_core_thread_backstop_v56")
MARKER = "20260808-writer-runtime-core-thread-backstop-v56"

_LOCK = threading.RLock()
_INSTALLED = False
_PATCH_ATTR = "_nija_writer_runtime_core_thread_backstop_v56"
_ENTRYPOINT_NAMES = ("bot.entrypoint_writer_authority", "entrypoint_writer_authority")


def _thread_alive(thread: Any) -> bool:
    if thread is None or not callable(getattr(thread, "is_alive", None)):
        return False
    try:
        return bool(thread.is_alive())
    except Exception:
        return False


def _entrypoint_runtime() -> Any:
    seen: set[int] = set()
    for name in _ENTRYPOINT_NAMES:
        module = sys.modules.get(name)
        if not isinstance(module, ModuleType):
            try:
                module = importlib.import_module(name)
            except Exception:
                continue
        if id(module) in seen:
            continue
        seen.add(id(module))
        getter = getattr(module, "get_entrypoint_writer_authority", None)
        if not callable(getter):
            continue
        try:
            runtime = getter()
        except Exception:
            continue
        if runtime is not None:
            return runtime
    return None


def _canonical_core_thread_alive(module: ModuleType | None = None) -> bool:
    """Return true when either canonical core-thread reference is alive."""
    module = module or sys.modules.get("bot.bot_main")
    if isinstance(module, ModuleType) and _thread_alive(
        getattr(module, "_core_loop_thread", None)
    ):
        return True

    runtime = _entrypoint_runtime()
    if runtime is not None and _thread_alive(getattr(runtime, "_core_thread", None)):
        return True
    return False


setattr(_canonical_core_thread_alive, _PATCH_ATTR, True)


def install_import_hook() -> bool:
    global _INSTALLED
    with _LOCK:
        try:
            v54 = importlib.import_module("bot.writer_runtime_lifecycle_supervisor_v54_patch")
        except Exception as exc:
            LOGGER.critical(
                "WRITER_RUNTIME_V56_INSTALL_FAILED marker=%s reason=v54_import error=%s:%s",
                MARKER,
                type(exc).__name__,
                exc,
            )
            return False

        current = getattr(v54, "_core_thread_alive", None)
        if getattr(current, _PATCH_ATTR, False):
            _INSTALLED = True
            os.environ["NIJA_WRITER_RUNTIME_CORE_THREAD_BACKSTOP_V56_INSTALLED"] = "1"
            return True
        if not callable(current):
            LOGGER.critical(
                "WRITER_RUNTIME_V56_INSTALL_FAILED marker=%s reason=v54_core_observer_missing",
                MARKER,
            )
            return False

        setattr(_canonical_core_thread_alive, "__wrapped__", current)
        v54._core_thread_alive = _canonical_core_thread_alive
        _INSTALLED = True
        os.environ["NIJA_WRITER_RUNTIME_CORE_THREAD_BACKSTOP_V56_INSTALLED"] = "1"
        LOGGER.critical(
            "WRITER_RUNTIME_V56_BACKSTOP_INSTALLED marker=%s "
            "bot_main_core=true writer_registered_core=true lock_mutation=false "
            "v54_shutdown_semantics=preserved v39_recovery_semantics=preserved",
            MARKER,
        )
        return True


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "_canonical_core_thread_alive",
]
