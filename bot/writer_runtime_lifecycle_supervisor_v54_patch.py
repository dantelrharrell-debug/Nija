"""Writer runtime lifecycle supervisor v54.

Production on the v53 build exposed a half-live process: the canonical writer
lease had been released (`writer_lease_not_acquired`) while the process later
started the core scan loop. Order submission remained protected by downstream
writer assertions, but scanning should never start or remain alive without a
proven process-writer lease.

v54 adds two fail-closed invariants without acquiring or mutating a writer lock:

1. `start_trading_engine()` is blocked unless v45 proves the current canonical
   EntrypointWriterAuthority owns the exact Redis process-writer lock with a
   positive generation.
2. Once the core thread exists, a process-lifetime supervisor repeatedly checks
   that same proof. If authority disappears and v39 bounded writer re-election
   is not active, it clears execution claims and sets bot_main's shutdown event
   so the canonical process exits through its normal cleanup path.

The supervisor never creates, renews, deletes, extends, or steals a Redis lock.
It never fabricates capital, generation, heartbeat, broker readiness, or order
permission. During an active v39 re-election window it remains fail-closed but
allows the existing bounded recovery path to finish.
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

LOGGER = logging.getLogger("nija.writer_runtime_lifecycle_supervisor_v54")
MARKER = "20260808-writer-runtime-lifecycle-supervisor-v54"

_LOCK = threading.RLock()
_STOP = threading.Event()
_STARTED = False
_IMPORT_FLAG = "_NIJA_WRITER_RUNTIME_LIFECYCLE_V54_IMPORT_HOOK"
_IMPORTLIB_FLAG = "_NIJA_WRITER_RUNTIME_LIFECYCLE_V54_IMPORTLIB_HOOK"
_START_PATCH = "_nija_writer_runtime_lifecycle_v54_start"
_CORE_NAMES = {"bot.nija_core_loop", "nija_core_loop"}


def _fail_closed() -> None:
    os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] = "0"
    os.environ["NIJA_EXECUTION_ACTIVE"] = "false"


def _writer_proof() -> tuple[bool, str, int]:
    try:
        module = importlib.import_module("bot.writer_generation_handoff_v45_patch")
        prove = getattr(module, "_prove_process_writer", None)
        if not callable(prove):
            return False, "v45_process_writer_proof_unavailable", 0
        proof, reason = prove()
        if proof is None:
            return False, str(reason or "process_writer_proof_failed"), 0
        generation = int(proof.get("generation", 0) or 0)
        token = str(proof.get("token", "") or "").strip()
        if generation <= 0:
            return False, "canonical_generation_invalid", generation
        if not token:
            return False, "canonical_fencing_token_missing", generation
        return True, "exact_redis_process_writer", generation
    except Exception as exc:
        return False, f"process_writer_proof_error:{type(exc).__name__}:{exc}", 0


def _v39_recovery_active() -> bool:
    module = sys.modules.get("bot.production_readiness_v39_patch") or sys.modules.get(
        "production_readiness_v39_patch"
    )
    if not isinstance(module, ModuleType):
        return False
    try:
        lock = getattr(module, "_RECOVERY_LOCK", None)
        if lock is not None:
            with lock:
                return bool(getattr(module, "_RECOVERY_ACTIVE", False))
    except Exception:
        pass
    return bool(getattr(module, "_RECOVERY_ACTIVE", False))


def _bot_main() -> ModuleType | None:
    module = sys.modules.get("bot.bot_main")
    return module if isinstance(module, ModuleType) else None


def _core_thread_alive(module: ModuleType | None = None) -> bool:
    module = module or _bot_main()
    if module is None:
        return False
    thread = getattr(module, "_core_loop_thread", None)
    if thread is None or not callable(getattr(thread, "is_alive", None)):
        return False
    try:
        return bool(thread.is_alive())
    except Exception:
        return False


def _request_canonical_shutdown(reason: str) -> bool:
    _fail_closed()
    module = _bot_main()
    if module is None:
        LOGGER.critical(
            "WRITER_RUNTIME_V54_SHUTDOWN_DEFERRED marker=%s reason=%s bot_main_missing=true",
            MARKER,
            reason,
        )
        return False
    shutdown = getattr(module, "_shutdown_event", None)
    setter = getattr(shutdown, "set", None)
    if not callable(setter):
        LOGGER.critical(
            "WRITER_RUNTIME_V54_SHUTDOWN_DEFERRED marker=%s reason=%s shutdown_event_missing=true",
            MARKER,
            reason,
        )
        return False
    setter()
    LOGGER.critical(
        "WRITER_RUNTIME_V54_SHUTDOWN_REQUESTED marker=%s reason=%s core_thread_alive=%s "
        "execution_fail_closed=true normal_cleanup=true",
        MARKER,
        reason,
        _core_thread_alive(module),
    )
    return True


def _patch_core_loop(module: ModuleType) -> bool:
    current = getattr(module, "start_trading_engine", None)
    if not callable(current):
        return False
    if getattr(current, _START_PATCH, False):
        return True
    original = current

    @wraps(original)
    def start_trading_engine(*args: Any, **kwargs: Any):
        ok, reason, generation = _writer_proof()
        if not ok:
            _fail_closed()
            LOGGER.critical(
                "WRITER_RUNTIME_V54_CORE_START_BLOCKED marker=%s reason=%s generation=%s "
                "trading_loop_started=false",
                MARKER,
                reason,
                generation,
            )
            raise RuntimeError(f"writer_runtime_v54_core_start_blocked:{reason}")
        LOGGER.critical(
            "WRITER_RUNTIME_V54_CORE_START_PROVEN marker=%s generation=%s proof=%s",
            MARKER,
            generation,
            reason,
        )
        return original(*args, **kwargs)

    setattr(start_trading_engine, _START_PATCH, True)
    setattr(start_trading_engine, "__wrapped__", original)
    module.start_trading_engine = start_trading_engine
    LOGGER.critical(
        "WRITER_RUNTIME_V54_CORE_PATCHED marker=%s module=%s prestart_exact_writer_proof=true",
        MARKER,
        module.__name__,
    )
    return True


def _patch_loaded() -> bool:
    changed = False
    seen: set[int] = set()
    for name in _CORE_NAMES:
        module = sys.modules.get(name)
        if not isinstance(module, ModuleType) or id(module) in seen:
            continue
        seen.add(id(module))
        changed = _patch_core_loop(module) or changed
    return changed


def _supervisor_loop() -> None:
    last_signature = ""
    while not _STOP.wait(2.0):
        module = _bot_main()
        if not _core_thread_alive(module):
            continue
        ok, reason, generation = _writer_proof()
        if ok:
            signature = f"ok:{generation}"
            if signature != last_signature:
                last_signature = signature
                LOGGER.info(
                    "WRITER_RUNTIME_V54_SUPERVISOR marker=%s state=proven generation=%s",
                    MARKER,
                    generation,
                )
            continue

        _fail_closed()
        if _v39_recovery_active():
            signature = f"recovering:{reason}"
            if signature != last_signature:
                last_signature = signature
                LOGGER.warning(
                    "WRITER_RUNTIME_V54_SUPERVISOR marker=%s state=writer_recovery_active "
                    "reason=%s generation=%s execution_fail_closed=true",
                    MARKER,
                    reason,
                    generation,
                )
            continue

        _request_canonical_shutdown(reason)
        return


def _interesting(name: str) -> bool:
    return str(name or "") in _CORE_NAMES


def install_import_hook() -> bool:
    global _STARTED
    with _LOCK:
        _patch_loaded()
        if not getattr(builtins, _IMPORT_FLAG, False):
            original_import = builtins.__import__

            @wraps(original_import)
            def importing(
                name: str,
                globals: Any = None,
                locals: Any = None,
                fromlist: Any = (),
                level: int = 0,
            ):
                result = original_import(name, globals, locals, fromlist, level)
                if _interesting(name):
                    _patch_loaded()
                return result

            builtins.__import__ = importing
            setattr(builtins, _IMPORT_FLAG, True)

        if not getattr(importlib, _IMPORTLIB_FLAG, False):
            original_import_module = importlib.import_module

            @wraps(original_import_module)
            def import_module(name: str, package: str | None = None):
                result = original_import_module(name, package)
                if _interesting(name):
                    _patch_loaded()
                return result

            importlib.import_module = import_module  # type: ignore[assignment]
            setattr(importlib, _IMPORTLIB_FLAG, True)

        if not _STARTED:
            _STOP.clear()
            threading.Thread(
                target=_supervisor_loop,
                name="WriterRuntimeLifecycleSupervisorV54",
                daemon=True,
            ).start()
            _STARTED = True

        os.environ["NIJA_WRITER_RUNTIME_LIFECYCLE_V54_INSTALLED"] = "1"
        LOGGER.critical(
            "WRITER_RUNTIME_LIFECYCLE_V54_INSTALLED marker=%s prestart_gate=true "
            "process_lifetime_supervisor=true lock_mutation=false",
            MARKER,
        )
        return True


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "_writer_proof",
    "_patch_core_loop",
    "_request_canonical_shutdown",
]
