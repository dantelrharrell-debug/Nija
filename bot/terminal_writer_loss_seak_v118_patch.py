"""Terminal writer-loss SEAK compatibility repair v118.

Production logs showed terminal_writer_loss_latch passing a ``source`` keyword
to SingleExecutionAuthorityKernel.emergency_halt(), whose canonical signature
accepts only ``reason``.  The resulting TypeError did not reopen execution, but
it prevented the terminal-loss latch from performing its own SEAK halt step.

v118 replaces only that helper.  It preserves the existing terminal-loss
classification, readiness revocation, global shutdown, and process-exit flow.
No writer authority, readiness, nonce state, capital, position state, or
execution permission is fabricated.
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

LOGGER = logging.getLogger("nija.terminal_writer_loss_seak_v118")
MARKER = "20260816-terminal-writer-loss-seak-v118"
_LOCK = threading.RLock()
_IMPORT_LOCAL = threading.local()
_IMPORT_FLAG = "_NIJA_TERMINAL_WRITER_LOSS_SEAK_V118_IMPORT_HOOK"
_PATCH_ATTR = "_nija_terminal_writer_loss_seak_v118"


def _loaded(*names: str) -> ModuleType | None:
    for name in names:
        mod = sys.modules.get(name)
        if isinstance(mod, ModuleType):
            return mod
    return None


def _patch_terminal_latch() -> bool:
    mod = _loaded("bot.terminal_writer_loss_latch", "terminal_writer_loss_latch")
    if mod is None:
        return True

    current = getattr(mod, "_halt_seak_on_terminal_loss", None)
    if not callable(current):
        return False
    if getattr(current, _PATCH_ATTR, False):
        return True

    def halt_seak_compatible(reason: str) -> None:
        try:
            try:
                from bot.single_execution_authority_kernel import get_seak
            except ImportError:
                from single_execution_authority_kernel import get_seak  # type: ignore[import]
            seak = get_seak()
            if seak is None:
                return
            halt = getattr(seak, "emergency_halt", None)
            if not callable(halt):
                return
            halt(f"terminal_writer_loss:{reason}")
            LOGGER.critical(
                "TERMINAL_WRITER_LOSS_SEAK_V118_HALTED marker=%s reason=%s source=terminal_writer_loss_latch execution_fail_closed=true",
                MARKER,
                reason,
            )
        except Exception as exc:
            LOGGER.critical(
                "TERMINAL_WRITER_LOSS_SEAK_V118_FAILED marker=%s err=%s execution_fail_closed=true",
                MARKER,
                exc,
                exc_info=True,
            )

    setattr(halt_seak_compatible, _PATCH_ATTR, True)
    setattr(halt_seak_compatible, "__wrapped__", current)
    mod._halt_seak_on_terminal_loss = halt_seak_compatible
    return True


def _patch_loaded() -> bool:
    return _patch_terminal_latch()


def install_import_hook() -> bool:
    with _LOCK:
        ready = _patch_loaded()
        if not getattr(builtins, _IMPORT_FLAG, False):
            original_import = builtins.__import__

            @wraps(original_import)
            def importing(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
                result = original_import(name, globals, locals, fromlist, level)
                if getattr(_IMPORT_LOCAL, "active", False):
                    return result
                if "terminal_writer_loss_latch" in str(name or ""):
                    _IMPORT_LOCAL.active = True
                    try:
                        _patch_loaded()
                    finally:
                        _IMPORT_LOCAL.active = False
                return result

            builtins.__import__ = importing
            setattr(builtins, _IMPORT_FLAG, True)

        os.environ["NIJA_TERMINAL_WRITER_LOSS_SEAK_V118_INSTALLED"] = "1"
        LOGGER.critical(
            "TERMINAL_WRITER_LOSS_SEAK_V118_INSTALLED marker=%s emergency_halt_signature_compatible=true safety_gates_unchanged=true initial_patch_ready=%s",
            MARKER,
            ready,
        )
        return True


def install() -> bool:
    return install_import_hook()


__all__ = ["MARKER", "install", "install_import_hook"]
