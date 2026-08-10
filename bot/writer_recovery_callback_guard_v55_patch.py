"""Writer recovery callback/lifecycle guard v55.

Repairs two fail-closed writer lifecycle gaps observed after v54:

* recoverable distributed writer loss can be detected by v52 while the runtime's
  on-lost callback no longer points at v39's bounded fresh-epoch recovery path;
* v53 invalidates ``_lost`` immediately before canonical ``release()`` sets the
  stop event, leaving a small window where the heartbeat can observe lost state
  as a heartbeat failure instead of an intentional quiesced release.

v55 never grants writer authority. It composes the canonical loss callback so
only reasons already accepted by v39/v46 enter the existing bounded recovery
routine, while every non-recoverable reason keeps the prior callback/shutdown
behavior. It also sets the writer stop event before delegating to the existing
release stack, so intentional release is quiesced before v53 exposes lost state.
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

LOGGER = logging.getLogger("nija.writer_recovery_callback_guard_v55")
MARKER = "20260808-writer-recovery-callback-guard-v55"

_LOCK = threading.RLock()
_STOP = threading.Event()
_STARTED = False
_IMPORT_FLAG = "_NIJA_WRITER_RECOVERY_CALLBACK_V55_IMPORT_HOOK"
_IMPORTLIB_FLAG = "_NIJA_WRITER_RECOVERY_CALLBACK_V55_IMPORTLIB_HOOK"
_MARK_PATCH = "_nija_writer_recovery_callback_v55_mark_lost"
_SETTER_PATCH = "_nija_writer_recovery_callback_v55_setter"
_RELEASE_PATCH = "_nija_writer_recovery_callback_v55_release"
_CALLBACK_PATCH = "_nija_writer_recovery_callback_v55_callback"
_TARGETS = {"bot.entrypoint_writer_authority", "entrypoint_writer_authority"}


def _fail_closed() -> None:
    os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] = "0"
    os.environ["NIJA_EXECUTION_ACTIVE"] = "false"


def _bot_main() -> ModuleType | None:
    module = sys.modules.get("bot.bot_main")
    if isinstance(module, ModuleType):
        return module
    try:
        module = importlib.import_module("bot.bot_main")
    except Exception:
        return None
    return module if isinstance(module, ModuleType) else None


def _v39() -> ModuleType | None:
    for name in (
        "bot.production_readiness_v39_patch",
        "production_readiness_v39_patch",
    ):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            return module
    try:
        module = importlib.import_module("bot.production_readiness_v39_patch")
    except Exception:
        return None
    return module if isinstance(module, ModuleType) else None


def _recoverable(reason: str) -> bool:
    text = str(reason or "")
    if "core_thread_" in text:
        return False
    module = _v39()
    predicate = getattr(module, "_recoverable_writer_loss", None) if module else None
    if callable(predicate):
        try:
            return bool(predicate(text))
        except Exception:
            pass
    return bool(
        "lock_missing_and_fencing_token_mismatch" in text
        or "writer_lock_released_for_reelection:authority_invariant_violated:"
        in text
    )


def _recovery_active() -> bool:
    module = _v39()
    if module is None:
        return False
    lock = getattr(module, "_RECOVERY_LOCK", None)
    try:
        if lock is not None:
            with lock:
                return bool(getattr(module, "_RECOVERY_ACTIVE", False))
    except Exception:
        pass
    return bool(getattr(module, "_RECOVERY_ACTIVE", False))


def _stop_authority_monitor(bot_main: ModuleType | None) -> None:
    if bot_main is None:
        return
    monitor = getattr(bot_main, "_authority_heartbeat_monitor", None)
    stop = getattr(monitor, "stop", None)
    if callable(stop):
        try:
            stop()
        except Exception:
            pass


def _fallback_shutdown(reason: str) -> None:
    _fail_closed()
    bot_main = _bot_main()
    shutdown = (
        getattr(bot_main, "_shutdown_event", None)
        if bot_main is not None
        else None
    )
    setter = getattr(shutdown, "set", None)
    if callable(setter):
        setter()
    scheduler = (
        getattr(bot_main, "_schedule_writer_authority_restart", None)
        if bot_main is not None
        else None
    )
    if not callable(scheduler) and bot_main is not None:
        scheduler = getattr(bot_main, "_schedule_core_registration_restart", None)
    restart_scheduled = False
    if callable(scheduler):
        try:
            scheduler(str(reason or "v55_writer_recovery_failed"))
            restart_scheduled = True
        except Exception as exc:
            LOGGER.error(
                "WRITER_RECOVERY_V55_RESTART_SCHEDULE_FAILED marker=%s "
                "reason=%s err=%s:%s",
                MARKER,
                str(reason or "unknown"),
                type(exc).__name__,
                exc,
            )
    LOGGER.critical(
        "WRITER_RECOVERY_V55_SHUTDOWN marker=%s reason=%s "
        "execution_fail_closed=true restart_scheduled=%s",
        MARKER,
        str(reason or "unknown"),
        restart_scheduled,
    )


def _start_recovery(runtime: Any, reason: str) -> bool:
    if not _recoverable(reason):
        return False
    module = _v39()
    starter = (
        getattr(module, "_start_writer_recovery", None)
        if module is not None
        else None
    )
    bot_main = _bot_main()
    if not callable(starter) or bot_main is None:
        LOGGER.critical(
            "WRITER_RECOVERY_V55_UNAVAILABLE marker=%s reason=%s v39=%s "
            "bot_main=%s fail_closed=true",
            MARKER,
            reason,
            bool(module),
            bool(bot_main),
        )
        return False
    _fail_closed()
    _stop_authority_monitor(bot_main)
    try:
        started = bool(starter(bot_main, runtime, reason, _fallback_shutdown))
    except Exception as exc:
        LOGGER.error(
            "WRITER_RECOVERY_V55_START_FAILED marker=%s reason=%s err=%s:%s",
            MARKER,
            reason,
            type(exc).__name__,
            exc,
        )
        return False
    LOGGER.critical(
        "WRITER_RECOVERY_V55_HANDOFF marker=%s reason=%s started=%s "
        "bounded_v39=true execution_fail_closed=true",
        MARKER,
        reason,
        started,
    )
    return started


def _compose_callback(runtime: Any, callback: Any) -> Any:
    if callable(callback) and bool(getattr(callback, _CALLBACK_PATCH, False)):
        return callback

    def guarded(reason: str) -> None:
        text = str(reason or "")
        if _recoverable(text):
            if _start_recovery(runtime, text):
                return
            _fallback_shutdown(f"v55_recovery_start_failed:{text}")
            return
        if callable(callback):
            callback(text)
            return
        _fallback_shutdown(f"v55_nonrecoverable_without_callback:{text}")

    setattr(guarded, _CALLBACK_PATCH, True)
    setattr(guarded, "_nija_prior_callback", callback)
    return guarded


def _patch_entrypoint_module(module: ModuleType) -> bool:
    cls = getattr(module, "EntrypointWriterAuthority", None)
    if not isinstance(cls, type):
        return False
    changed = False

    current_setter = getattr(cls, "set_on_lost_callback", None)
    if callable(current_setter) and not bool(
        getattr(current_setter, _SETTER_PATCH, False)
    ):
        original_setter = current_setter

        @wraps(original_setter)
        def set_on_lost_callback(self: Any, callback: Any) -> Any:
            return original_setter(self, _compose_callback(self, callback))

        setattr(set_on_lost_callback, _SETTER_PATCH, True)
        setattr(set_on_lost_callback, "__wrapped__", original_setter)
        cls.set_on_lost_callback = set_on_lost_callback
        changed = True

    current_mark = getattr(cls, "_mark_lost", None)
    if callable(current_mark) and not bool(getattr(current_mark, _MARK_PATCH, False)):
        original_mark = current_mark

        @wraps(original_mark)
        def mark_lost(self: Any, reason: str) -> Any:
            callback = getattr(self, "_on_lost_callback", None)
            if not (
                callable(callback)
                and bool(getattr(callback, _CALLBACK_PATCH, False))
            ):
                setattr(
                    self,
                    "_on_lost_callback",
                    _compose_callback(self, callback),
                )
            result = original_mark(self, reason)
            if _recoverable(reason) and not _recovery_active():
                if not _start_recovery(self, reason):
                    _fallback_shutdown(
                        f"v55_post_mark_recovery_failed:{reason}"
                    )
            return result

        setattr(mark_lost, _MARK_PATCH, True)
        setattr(mark_lost, "__wrapped__", original_mark)
        cls._mark_lost = mark_lost
        changed = True

    current_release = getattr(cls, "release", None)
    if callable(current_release) and not bool(
        getattr(current_release, _RELEASE_PATCH, False)
    ):
        original_release = current_release

        @wraps(original_release)
        def release(self: Any, *args: Any, **kwargs: Any) -> Any:
            stop = getattr(self, "_stop", None)
            setter = getattr(stop, "set", None)
            if callable(setter):
                setter()
            _fail_closed()
            LOGGER.info(
                "WRITER_RECOVERY_V55_RELEASE_QUIESCED marker=%s "
                "stop_before_lost=true execution_fail_closed=true",
                MARKER,
            )
            return original_release(self, *args, **kwargs)

        setattr(release, _RELEASE_PATCH, True)
        setattr(release, "__wrapped__", original_release)
        cls.release = release
        changed = True

    return changed or bool(
        callable(getattr(cls, "_mark_lost", None))
        and getattr(getattr(cls, "_mark_lost"), _MARK_PATCH, False)
    )


def _runtime() -> Any:
    for name in _TARGETS:
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


def reconcile_once() -> dict[str, Any]:
    runtime = _runtime()
    if runtime is None:
        return {"ok": False, "action": "runtime_unavailable"}

    callback = getattr(runtime, "_on_lost_callback", None)
    if not (
        callable(callback) and bool(getattr(callback, _CALLBACK_PATCH, False))
    ):
        setattr(
            runtime,
            "_on_lost_callback",
            _compose_callback(runtime, callback),
        )
        LOGGER.warning(
            "WRITER_RECOVERY_V55_CALLBACK_REPAIRED marker=%s callback_drift=true",
            MARKER,
        )

    lost = bool(getattr(runtime, "lost", False))
    stop = getattr(runtime, "_stop", None)
    stopped = bool(getattr(stop, "is_set", lambda: False)())
    if lost and not stopped and not _recovery_active():
        reason = str(os.environ.get("NIJA_WRITER_LAST_LOSS_REASON", "") or "")
        if _recoverable(reason):
            if _start_recovery(runtime, reason):
                return {
                    "ok": True,
                    "action": "recovery_backstop_started",
                    "reason": reason,
                }
            _fallback_shutdown(f"v55_backstop_recovery_failed:{reason}")
            return {"ok": False, "action": "shutdown", "reason": reason}

    return {"ok": True, "action": "callback_guarded"}


def _patch_loaded() -> bool:
    ok = False
    seen: set[int] = set()
    for name in _TARGETS:
        module = sys.modules.get(name)
        if not isinstance(module, ModuleType) or id(module) in seen:
            continue
        seen.add(id(module))
        ok = _patch_entrypoint_module(module) or ok
    return ok


def _interesting(name: str) -> bool:
    text = str(name or "")
    return text in _TARGETS or text in {
        "bot.bot_main",
        "bot.production_readiness_v39_patch",
        "production_readiness_v39_patch",
    }


def _supervisor_loop() -> None:
    while not _STOP.wait(1.0):
        try:
            _patch_loaded()
            reconcile_once()
        except Exception as exc:
            _fail_closed()
            LOGGER.warning(
                "WRITER_RECOVERY_V55_SUPERVISOR_ERROR marker=%s err=%s:%s "
                "fail_closed=true",
                MARKER,
                type(exc).__name__,
                exc,
            )


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
                name="WriterRecoveryCallbackGuardV55",
                daemon=True,
            ).start()
            _STARTED = True

        os.environ["NIJA_WRITER_RECOVERY_CALLBACK_V55_INSTALLED"] = "1"
        LOGGER.critical(
            "WRITER_RECOVERY_CALLBACK_V55_INSTALLED marker=%s bounded_v39=true "
            "callback_guard=true release_quiesce=true lock_grant=false",
            MARKER,
        )
        return True


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "_recoverable",
    "_start_recovery",
    "_compose_callback",
    "_patch_entrypoint_module",
    "reconcile_once",
]
