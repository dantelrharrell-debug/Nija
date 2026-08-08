"""NIJA writer re-election loss-reason convergence v46.

Production after the v39 wrapper-preservation fix still exposed a zero-generation
writer state. ``EntrypointWriterAuthority`` intentionally releases its own exact
Redis lock and marks itself lost when a process-local authority invariant is
violated, using a reason of the form::

    writer_lock_released_for_reelection:authority_invariant_violated:...

That path is explicitly a request for a fresh writer election, but v39 only
classified ``lock_missing_and_fencing_token_mismatch`` as recoverable. The
intentional re-election reason therefore fell through to the original shutdown
callback and left downstream heartbeat/Kraken recovery readers with generation 0.

v46 does not grant writer authority and does not create, extend, steal, or rewrite
any Redis lock. It only lets v39's existing bounded re-election flow run for the
runtime's explicit authority-invariant re-election reason. That existing flow must
still acquire a fresh Redis lease, synchronously verify distributed authority,
restart the authority monitor, and prove SEAK eligibility before execution can
resume. Dead-core, arbitrary heartbeat, manual stop, and unrelated Redis failures
remain non-recoverable.

The patch also publishes the exact last writer-loss reason and timestamp before
the canonical loss handler clears generation/token telemetry. Those fields are
observability only and are never consumed as authority proof.
"""
from __future__ import annotations

import builtins
import importlib
import logging
import os
import sys
import threading
import time
from functools import wraps
from types import ModuleType
from typing import Any

LOGGER = logging.getLogger("nija.writer_reelection_loss_reason_v46")
MARKER = "20260808-writer-reelection-loss-reason-v46"

_V39_MARKER = "20260807-production-readiness-v39"
_SAFE_REELECTION_TOKEN = (
    "writer_lock_released_for_reelection:authority_invariant_violated:"
)
_V39_PATCH = "_nija_writer_reelection_loss_reason_v46"
_ENTRYPOINT_PATCH = "_nija_writer_loss_observability_v46"
_IMPORT_HOOK_FLAG = "_NIJA_WRITER_REELECTION_LOSS_REASON_V46_IMPORT_HOOK"
_IMPORTLIB_HOOK_FLAG = "_NIJA_WRITER_REELECTION_LOSS_REASON_V46_IMPORTLIB_HOOK"
_LOCK = threading.RLock()
_INSTALLED = False


def _newly_recoverable_reason(reason: str) -> bool:
    """Return True only for the canonical intentional invariant re-election path."""

    text = str(reason or "")
    if _SAFE_REELECTION_TOKEN not in text:
        return False
    # Core-thread loss is intentionally terminal for this process. Even if a
    # future caller wraps that reason, v46 must never use writer re-election to
    # mask a dead execution worker.
    if "core_thread_" in text:
        return False
    return True


def _safe_recoverable_reason(reason: str) -> bool:
    """Mirror v39's existing case plus v46's one narrow re-election case."""

    text = str(reason or "")
    return bool(
        "lock_missing_and_fencing_token_mismatch" in text
        or _newly_recoverable_reason(text)
    )


def _patch_v39_module(module: ModuleType) -> bool:
    current = getattr(module, "_recoverable_writer_loss", None)
    if not callable(current):
        return False
    if bool(getattr(current, _V39_PATCH, False)):
        return True

    @wraps(current)
    def recoverable_writer_loss(reason: str) -> bool:
        if bool(current(reason)):
            return True
        if not _newly_recoverable_reason(reason):
            return False
        LOGGER.critical(
            "WRITER_REELECTION_V46_REASON_ACCEPTED marker=%s reason=%s "
            "safety=existing_v39_bounded_redis_proven_flow",
            MARKER,
            str(reason or ""),
        )
        return True

    setattr(recoverable_writer_loss, _V39_PATCH, True)
    setattr(recoverable_writer_loss, "__wrapped__", current)
    setattr(module, "_recoverable_writer_loss", recoverable_writer_loss)
    LOGGER.critical(
        "WRITER_REELECTION_V46_V39_PATCHED marker=%s module=%s",
        MARKER,
        module.__name__,
    )
    return True


def _patch_entrypoint_module(module: ModuleType) -> bool:
    cls = getattr(module, "EntrypointWriterAuthority", None)
    if not isinstance(cls, type):
        return False
    current = getattr(cls, "_mark_lost", None)
    if not callable(current):
        return False
    if bool(getattr(current, _ENTRYPOINT_PATCH, False)):
        return True

    @wraps(current)
    def mark_lost(self: Any, reason: str) -> Any:
        text = str(reason or "")
        recoverable = _safe_recoverable_reason(text)
        os.environ["NIJA_WRITER_LAST_LOSS_REASON"] = text
        os.environ["NIJA_WRITER_LAST_LOSS_TS"] = str(time.time())
        os.environ["NIJA_WRITER_LAST_LOSS_RECOVERABLE"] = "1" if recoverable else "0"
        LOGGER.critical(
            "WRITER_LOSS_V46_OBSERVED marker=%s recoverable=%s reason=%s",
            MARKER,
            recoverable,
            text,
        )
        return current(self, reason)

    setattr(mark_lost, _ENTRYPOINT_PATCH, True)
    setattr(mark_lost, "__wrapped__", current)
    setattr(cls, "_mark_lost", mark_lost)
    LOGGER.critical(
        "WRITER_LOSS_V46_OBSERVABILITY_PATCHED marker=%s module=%s",
        MARKER,
        module.__name__,
    )
    return True


def _is_v39_module(module: ModuleType) -> bool:
    return bool(
        str(getattr(module, "MARKER", "") or "") == _V39_MARKER
        or module.__name__.endswith("production_readiness_v39_patch")
        or module.__name__ == "nija_production_readiness_v39_prebot"
    )


def _is_entrypoint_module(module: ModuleType) -> bool:
    return module.__name__ in {
        "bot.entrypoint_writer_authority",
        "entrypoint_writer_authority",
    }


def _patch_loaded() -> tuple[bool, bool]:
    v39_ok = False
    entrypoint_ok = False
    seen: set[int] = set()
    for module in list(sys.modules.values()):
        if not isinstance(module, ModuleType) or id(module) in seen:
            continue
        seen.add(id(module))
        try:
            if _is_v39_module(module):
                v39_ok = _patch_v39_module(module) or v39_ok
            if _is_entrypoint_module(module):
                entrypoint_ok = _patch_entrypoint_module(module) or entrypoint_ok
        except Exception as exc:
            LOGGER.warning(
                "WRITER_REELECTION_V46_PATCH_DEFERRED marker=%s module=%s err=%s:%s",
                MARKER,
                getattr(module, "__name__", "unknown"),
                type(exc).__name__,
                exc,
            )
    return v39_ok, entrypoint_ok


def _install_builtin_import_hook() -> None:
    if bool(getattr(builtins, _IMPORT_HOOK_FLAG, False)):
        return
    original_import = builtins.__import__

    @wraps(original_import)
    def importing(
        name: str,
        globals: Any = None,
        locals: Any = None,
        fromlist: Any = (),
        level: int = 0,
    ):
        module = original_import(name, globals, locals, fromlist, level)
        text = str(name or "")
        if "production_readiness_v39" in text or "entrypoint_writer_authority" in text:
            _patch_loaded()
        return module

    builtins.__import__ = importing
    setattr(builtins, _IMPORT_HOOK_FLAG, True)


def _install_importlib_hook() -> None:
    if bool(getattr(importlib, _IMPORTLIB_HOOK_FLAG, False)):
        return
    original_import_module = importlib.import_module

    @wraps(original_import_module)
    def import_module(name: str, package: str | None = None):
        module = original_import_module(name, package)
        text = str(name or "")
        if "production_readiness_v39" in text or "entrypoint_writer_authority" in text:
            _patch_loaded()
        return module

    importlib.import_module = import_module
    setattr(importlib, _IMPORTLIB_HOOK_FLAG, True)


def install_import_hook() -> bool:
    global _INSTALLED
    with _LOCK:
        v39_ok, entrypoint_ok = _patch_loaded()
        _install_builtin_import_hook()
        _install_importlib_hook()
        # The canonical launcher loads v46 immediately after v39, and v24 has
        # already caused bot_main/EntrypointWriterAuthority to load. Failing
        # either attachment here is therefore a startup-contract failure rather
        # than a reason to pretend the corrective layer is active.
        _INSTALLED = bool(v39_ok and entrypoint_ok)
        os.environ["NIJA_WRITER_REELECTION_LOSS_REASON_V46_INSTALLED"] = (
            "1" if _INSTALLED else "0"
        )
        LOGGER.critical(
            "WRITER_REELECTION_LOSS_REASON_V46_INSTALLED marker=%s v39_patched=%s "
            "entrypoint_patched=%s installed=%s",
            MARKER,
            v39_ok,
            entrypoint_ok,
            _INSTALLED,
        )
        return _INSTALLED


def install() -> bool:
    return install_import_hook()


__all__ = [
    "install",
    "install_import_hook",
    "_newly_recoverable_reason",
    "_safe_recoverable_reason",
    "_patch_v39_module",
    "_patch_entrypoint_module",
]
