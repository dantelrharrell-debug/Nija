"""Fail-closed writer epoch recovery guard.

A missing process writer lock is an ownership-epoch loss, not a TTL refresh.
This guard prevents EntrypointWriterAuthority from recreating a vanished lock
with the old fencing token. The existing heartbeat loop then marks authority
lost, bot_main stops execution, and the next canonical acquisition obtains a
fresh fencing token/generation.

v300 is chained here because this guard is installed before writer loss can be
observed.  The v300 companion binds callback-free fallback restart timers to the
loss epoch that created them, preventing a stale timer from terminating a
process after it has genuinely reacquired exact Redis writer authority.
"""
from __future__ import annotations
import builtins, importlib, logging, os, sys
from functools import wraps
from types import ModuleType
from typing import Any

LOGGER = logging.getLogger("nija.entrypoint_writer_epoch_recovery_v19")
MARKER = "20260807-writer-epoch-recovery-v19"
_FLAG = "_NIJA_WRITER_EPOCH_RECOVERY_V19_HOOK"

def _text(v: Any) -> str:
    return v.decode("utf-8", errors="replace") if isinstance(v, bytes) else str(v or "")

def _patch(module: ModuleType) -> bool:
    cls = getattr(module, "EntrypointWriterAuthority", None)
    if not isinstance(cls, type) or getattr(cls, "_nija_writer_epoch_recovery_v19", False):
        return False
    original = getattr(cls, "_heartbeat_tick", None)
    if not callable(original):
        return False
    @wraps(original)
    def _heartbeat_tick(self: Any):
        if not bool(getattr(self, "_local_fallback", False)):
            client = getattr(self, "_client", None)
            lock_key = str(getattr(self, "_lock_key", "") or "")
            lock_value = str(getattr(self, "_lock_value", "") or "")
            if client is not None and lock_key and lock_value:
                try:
                    current = _text(client.get(lock_key))
                except Exception as exc:
                    return False, f"redis_heartbeat_precheck_error:{type(exc).__name__}:{exc}"
                if not current:
                    LOGGER.critical("WRITER_EPOCH_LOCK_MISSING marker=%s lock_key=%s action=lose_authority", MARKER, lock_key)
                    return False, "lock_missing_and_fencing_token_mismatch"
                if current != lock_value:
                    LOGGER.critical("WRITER_EPOCH_OWNER_CHANGED marker=%s lock_key=%s action=lose_authority", MARKER, lock_key)
                    return False, "lock_owned_by_different_writer"
        return original(self)
    cls._heartbeat_tick = _heartbeat_tick
    cls._nija_writer_epoch_recovery_v19 = True
    os.environ["NIJA_WRITER_EPOCH_RECOVERY_V19_PATCHED"] = "1"
    return True

def _patch_loaded() -> bool:
    changed = False
    for name in ("bot.entrypoint_writer_authority", "entrypoint_writer_authority"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            changed = _patch(module) or changed
    return changed

def _install_v300() -> bool:
    """Install stale writer-loss restart protection without granting authority."""
    try:
        companion = importlib.import_module("bot.writer_reacquisition_restart_guard_v300_patch")
        installer = getattr(companion, "install_import_hook", None) or getattr(companion, "install", None)
        return bool(installer()) if callable(installer) else False
    except Exception as exc:
        LOGGER.error("WRITER_REACQUISITION_RESTART_GUARD_V300_INSTALL_FAILED marker=%s err=%s", MARKER, exc)
        return False

def install_import_hook() -> bool:
    _patch_loaded()
    if not getattr(builtins, _FLAG, False):
        original_import = builtins.__import__
        @wraps(original_import)
        def importing(name, globals=None, locals=None, fromlist=(), level=0):
            result = original_import(name, globals, locals, fromlist, level)
            if str(name).endswith("entrypoint_writer_authority"):
                _patch_loaded()
            return result
        builtins.__import__ = importing
        setattr(builtins, _FLAG, True)
    v300_ready = _install_v300()
    os.environ["NIJA_WRITER_EPOCH_RECOVERY_V19_INSTALLED"] = "1"
    LOGGER.critical(
        "WRITER_EPOCH_RECOVERY_V19_INSTALLED marker=%s fail_closed=true writer_reacquisition_restart_guard_v300=%s",
        MARKER,
        str(v300_ready).lower(),
    )
    return True

def install() -> bool:
    return install_import_hook()
