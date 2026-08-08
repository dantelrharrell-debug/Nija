"""NIJA writer lost-epoch convergence v48.

Production after v47 showed the process writer lock disappear while the runtime
still held the same fencing token/generation. The canonical heartbeat renewal
Lua path treated a missing lock plus matching fencing counter as recoverable and
recreated the missing lock with the stale epoch. That delayed the intended v40
-> v39 fresh-epoch recovery and allowed the recreated lock to expire again.

v48 makes missing-lock handling strictly fail-closed:
* exact current lock value -> delegate to the canonical renewal path;
* missing lock -> return lock_missing_and_fencing_token_mismatch so the existing
  heartbeat loop marks the runtime LOST and v39 performs fresh re-election;
* different lock value -> return lock_owned_by_different_writer;
* Redis read error -> fail closed without inferring ownership.

This patch never creates, extends, deletes, or steals a Redis writer lock. It
never changes broker, capital, SEAK, emergency-stop, readiness, risk, or
execution-dispatch gates.
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

LOGGER = logging.getLogger("nija.writer_lost_epoch_v48")
MARKER = "20260808-writer-lost-epoch-v48"

_LOCK = threading.RLock()
_PATCH_ATTR = "_nija_writer_lost_epoch_v48"
_INSTALL_FLAG = "_NIJA_WRITER_LOST_EPOCH_V48_IMPORT_HOOK"
_IMPORTLIB_FLAG = "_NIJA_WRITER_LOST_EPOCH_V48_IMPORTLIB_HOOK"
_TARGETS = {"bot.entrypoint_writer_authority", "entrypoint_writer_authority"}


def _text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value or "")


def _classify_current_lock(runtime: Any) -> tuple[str, str]:
    client = getattr(runtime, "_client", None)
    lock_key = str(getattr(runtime, "_lock_key", "") or "").strip()
    expected = str(getattr(runtime, "_lock_value", "") or "").strip()
    if client is None:
        return "error", "redis_client_missing"
    if not lock_key:
        return "error", "lock_key_missing"
    if not expected:
        return "error", "lock_value_missing"
    try:
        current = _text(client.get(lock_key)).strip()
    except Exception as exc:
        return "error", f"redis_lock_read_error:{type(exc).__name__}:{exc}"
    if not current:
        return "missing", f"lock_missing key={lock_key}"
    if current == expected:
        return "owned", f"lock_owned_exact key={lock_key}"
    return "other", f"lock_owned_by_other key={lock_key}"


def _patch_entrypoint_writer_authority(module: ModuleType) -> bool:
    cls = getattr(module, "EntrypointWriterAuthority", None)
    if not isinstance(cls, type):
        return False
    current = getattr(cls, "_heartbeat_tick", None)
    if not callable(current):
        return False
    if getattr(current, _PATCH_ATTR, False):
        return True

    original = current

    @wraps(original)
    def heartbeat_tick(self: Any) -> tuple[bool, str]:
        # A runtime already marked LOST must never be allowed to mutate or renew
        # writer state from a stale heartbeat worker.
        if bool(getattr(self, "lost", False)):
            os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] = "0"
            os.environ["NIJA_EXECUTION_ACTIVE"] = "false"
            return False, "runtime_already_lost"

        state, detail = _classify_current_lock(self)
        if state == "missing":
            os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] = "0"
            os.environ["NIJA_EXECUTION_ACTIVE"] = "false"
            LOGGER.critical(
                "WRITER_LOST_EPOCH_V48_MISSING marker=%s generation=%s token_prefix=%s detail=%s action=fresh_epoch_reelection",
                MARKER,
                getattr(self, "_generation", 0),
                str(getattr(self, "_token", "") or "")[:8],
                detail,
            )
            return False, "lock_missing_and_fencing_token_mismatch"
        if state == "other":
            os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] = "0"
            os.environ["NIJA_EXECUTION_ACTIVE"] = "false"
            LOGGER.critical(
                "WRITER_LOST_EPOCH_V48_OWNER_CHANGED marker=%s generation=%s detail=%s action=nonrecoverable_loss",
                MARKER,
                getattr(self, "_generation", 0),
                detail,
            )
            return False, "lock_owned_by_different_writer"
        if state == "error":
            os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] = "0"
            os.environ["NIJA_EXECUTION_ACTIVE"] = "false"
            return False, detail

        # Only an exact current lock value may reach the legacy renewal Lua.
        return original(self)

    setattr(heartbeat_tick, _PATCH_ATTR, True)
    setattr(heartbeat_tick, "__wrapped__", original)
    cls._heartbeat_tick = heartbeat_tick
    os.environ["NIJA_WRITER_LOST_EPOCH_V48_PATCHED"] = "1"
    LOGGER.critical(
        "WRITER_LOST_EPOCH_V48_PATCHED marker=%s module=%s missing_lock_recreate=false exact_owner_required=true",
        MARKER,
        module.__name__,
    )
    return True


def _patch_loaded() -> bool:
    patched = False
    seen: set[int] = set()
    for name in _TARGETS:
        module = sys.modules.get(name)
        if not isinstance(module, ModuleType) or id(module) in seen:
            continue
        seen.add(id(module))
        patched = _patch_entrypoint_writer_authority(module) or patched
    return patched


def install_import_hook() -> bool:
    with _LOCK:
        _patch_loaded()
        if not getattr(builtins, _INSTALL_FLAG, False):
            original_import = builtins.__import__

            @wraps(original_import)
            def importing(name: str, globals: Any = None, locals: Any = None, fromlist: Any = (), level: int = 0):
                result = original_import(name, globals, locals, fromlist, level)
                if str(name or "") in _TARGETS:
                    _patch_loaded()
                return result

            builtins.__import__ = importing
            setattr(builtins, _INSTALL_FLAG, True)

        if not getattr(importlib, _IMPORTLIB_FLAG, False):
            original_import_module = importlib.import_module

            @wraps(original_import_module)
            def import_module(name: str, package: str | None = None):
                result = original_import_module(name, package)
                if str(name or "") in _TARGETS:
                    _patch_loaded()
                return result

            importlib.import_module = import_module  # type: ignore[assignment]
            setattr(importlib, _IMPORTLIB_FLAG, True)

        os.environ["NIJA_WRITER_LOST_EPOCH_V48_INSTALLED"] = "1"
        LOGGER.critical(
            "WRITER_LOST_EPOCH_V48_INSTALLED marker=%s fail_closed=true stale_epoch_recreate=false",
            MARKER,
        )
        return True


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "_classify_current_lock",
    "_patch_entrypoint_writer_authority",
]
