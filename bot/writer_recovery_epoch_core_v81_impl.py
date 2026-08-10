"""Writer recovery epoch + real core-thread convergence v81.

Production on merge 4f758f3e showed two coupled liveness defects after a
recoverable distributed writer loss:

* v48 correctly marked the runtime lost for
  ``lock_missing_and_fencing_token_mismatch``.  While v39 was already performing
  bounded fresh-epoch recovery, the old heartbeat loop returned
  ``runtime_already_lost`` and the grace wrapper later emitted
  ``heartbeat_grace_expired:runtime_already_lost``.  v46 classified that
  secondary symptom as non-recoverable, allowing one incident to be reclassified
  as terminal during its own recovery window.
* after a successful fresh generation and broker recovery, activation remained
  ``LIVE_PENDING_CONFIRMATION`` because ``NIJA_CORE_THREAD_ALIVE`` was false.
  The runtime can have a valid canonical TradingStrategy while the original core
  thread reference is stale/dead.  v81 only reuses a genuinely alive core thread
  or restarts the engine from the already-published canonical strategy, verifies
  the returned thread is alive, and registers that exact thread with the writer.

Safety invariants:
* no Redis lock/token/generation is created or inferred by this module;
* arbitrary heartbeat failures remain non-recoverable;
* dead core-thread evidence is never converted to a synthetic alive flag;
* restart requires an acquired/non-lost writer, completed startup, a canonical
  published strategy, and no live registered core thread;
* all existing risk, emergency-stop, capital, broker and execution gates remain
  authoritative.
"""
from __future__ import annotations

import importlib
import logging
import os
import sys
import threading
import time
from functools import wraps
from types import ModuleType
from typing import Any

LOGGER = logging.getLogger("nija.writer_recovery_epoch_core_v81")
MARKER = "20260809-writer-recovery-epoch-core-v81"
_PATCH_ATTR = "_nija_writer_recovery_epoch_core_v81"
_LOCK = threading.RLock()
_RESTART_LOCK = threading.Lock()
_STOP = threading.Event()
_STARTED = False

_PRIMARY_TOKENS = (
    "lock_missing_and_fencing_token_mismatch",
    "writer_lock_released_for_reelection:authority_invariant_violated:",
)
_SECONDARY_REASON = "heartbeat_grace_expired:runtime_already_lost"


def _f(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value or 0.0)
    except (TypeError, ValueError, OverflowError):
        return default
    return result if result == result else default


def _thread_alive(thread: Any) -> bool:
    if thread is None or not callable(getattr(thread, "is_alive", None)):
        return False
    try:
        return bool(thread.is_alive())
    except Exception:
        return False


def _primary_recoverable(reason: str) -> bool:
    text = str(reason or "")
    if "core_thread_" in text:
        return False
    return any(token in text for token in _PRIMARY_TOKENS)


def _record_epoch(reason: str) -> None:
    if not _primary_recoverable(reason):
        return
    os.environ["NIJA_WRITER_RECOVERY_EPOCH_REASON"] = str(reason)
    os.environ["NIJA_WRITER_RECOVERY_EPOCH_TS"] = str(time.time())


def _epoch_window_s() -> float:
    # v39's normal recovery window plus enough room for the heartbeat grace
    # callback to observe the same incident.  Bounded by 10 minutes.
    base = max(5.0, _f(os.environ.get("NIJA_WRITER_REELECTION_MAX_S"), 120.0))
    grace = max(1.0, _f(os.environ.get("NIJA_WRITER_LOSS_GRACE_S"), 12.0))
    return min(600.0, base + grace + 15.0)


def _secondary_is_same_epoch(reason: str) -> bool:
    if str(reason or "") != _SECONDARY_REASON:
        return False
    primary = str(os.environ.get("NIJA_WRITER_RECOVERY_EPOCH_REASON", "") or "")
    if not _primary_recoverable(primary):
        return False
    started = _f(os.environ.get("NIJA_WRITER_RECOVERY_EPOCH_TS"), 0.0)
    if started <= 0.0:
        return False
    age = max(0.0, time.time() - started)
    return age <= _epoch_window_s()


def recoverable_reason(reason: str) -> bool:
    text = str(reason or "")
    if _primary_recoverable(text):
        _record_epoch(text)
        return True
    if _secondary_is_same_epoch(text):
        LOGGER.warning(
            "WRITER_V81_SECONDARY_LOSS_PRESERVED marker=%s reason=%s primary=%s age_s=%.1f",
            MARKER,
            text,
            os.environ.get("NIJA_WRITER_RECOVERY_EPOCH_REASON", ""),
            max(0.0, time.time() - _f(os.environ.get("NIJA_WRITER_RECOVERY_EPOCH_TS"), time.time())),
        )
        return True
    return False


def _patch_recovery_predicates() -> bool:
    changed = False
    targets = (
        ("bot.production_readiness_v39_patch", "_recoverable_writer_loss"),
        ("bot.writer_reelection_loss_reason_v46_patch", "_safe_recoverable_reason"),
    )
    for module_name, attr in targets:
        try:
            module = importlib.import_module(module_name)
        except Exception:
            continue
        current = getattr(module, attr, None)
        if not callable(current) or getattr(current, _PATCH_ATTR, False):
            continue

        @wraps(current)
        def wrapped(reason: str, __current=current):
            if bool(__current(reason)):
                if _primary_recoverable(reason):
                    _record_epoch(str(reason))
                return True
            return recoverable_reason(str(reason))

        setattr(wrapped, _PATCH_ATTR, True)
        setattr(wrapped, "__wrapped__", current)
        setattr(module, attr, wrapped)
        changed = True
        LOGGER.critical(
            "WRITER_V81_RECOVERY_PREDICATE_PATCHED marker=%s module=%s attr=%s",
            MARKER,
            module_name,
            attr,
        )
    return changed


def _runtime() -> Any:
    try:
        module = importlib.import_module("bot.entrypoint_writer_authority")
        getter = getattr(module, "get_entrypoint_writer_authority", None)
        return getter() if callable(getter) else None
    except Exception:
        return None


def _bot_main() -> ModuleType | None:
    module = sys.modules.get("bot.bot_main")
    if isinstance(module, ModuleType):
        return module
    try:
        module = importlib.import_module("bot.bot_main")
    except Exception:
        return None
    return module if isinstance(module, ModuleType) else None


def _live_core_thread(bot_main: ModuleType | None, runtime: Any) -> Any:
    for thread in (
        getattr(bot_main, "_core_loop_thread", None) if bot_main is not None else None,
        getattr(runtime, "_core_thread", None) if runtime is not None else None,
    ):
        if _thread_alive(thread):
            return thread
    return None


def _canonical_strategy() -> Any:
    try:
        module = importlib.import_module("bot.strategy_publication_patch")
    except Exception:
        return None
    strategy = getattr(module, "_PUBLISHED", None)
    if strategy is not None and callable(getattr(strategy, "run_cycle", None)):
        return strategy
    finder = getattr(module, "_existing", None)
    class_reader = getattr(module, "_strategy_class", None)
    if callable(finder):
        try:
            cls = class_reader() if callable(class_reader) else None
            strategy = finder(cls)
        except Exception:
            strategy = None
    return strategy if strategy is not None and callable(getattr(strategy, "run_cycle", None)) else None


def _register_real_core(bot_main: ModuleType, runtime: Any, thread: Any, source: str) -> bool:
    if not _thread_alive(thread):
        os.environ["NIJA_CORE_THREAD_ALIVE"] = "0"
        return False
    setattr(bot_main, "_core_loop_thread", thread)
    register = getattr(runtime, "register_core_thread", None)
    if not callable(register):
        return False
    register(thread)
    if not _thread_alive(thread):
        os.environ["NIJA_CORE_THREAD_ALIVE"] = "0"
        return False
    os.environ["NIJA_CORE_THREAD_ALIVE"] = "1"
    LOGGER.critical(
        "WRITER_V81_CORE_THREAD_BOUND marker=%s source=%s thread=%s ident=%s alive=true",
        MARKER,
        source,
        getattr(thread, "name", "unknown"),
        getattr(thread, "ident", None),
    )
    return True


def repair_core_thread_once() -> tuple[bool, str]:
    bot_main = _bot_main()
    runtime = _runtime()
    if bot_main is None or runtime is None:
        return False, "runtime_unavailable"
    if not bool(getattr(runtime, "acquired", False)) or bool(getattr(runtime, "lost", True)):
        return False, "writer_not_acquired"

    live = _live_core_thread(bot_main, runtime)
    if live is not None:
        return (_register_real_core(bot_main, runtime, live, "existing_live_thread"), "existing_live_thread")

    os.environ["NIJA_CORE_THREAD_ALIVE"] = "0"
    if not bool(getattr(bot_main, "_startup_complete", False)):
        return False, "startup_not_complete"
    shutdown = getattr(bot_main, "_shutdown_event", None)
    if shutdown is not None and callable(getattr(shutdown, "is_set", None)) and shutdown.is_set():
        return False, "shutdown_requested"

    strategy = _canonical_strategy()
    if strategy is None:
        return False, "canonical_strategy_unavailable"

    if not _RESTART_LOCK.acquire(blocking=False):
        return False, "restart_already_in_progress"
    try:
        # Re-check after acquiring the restart lock to prevent duplicate engines.
        live = _live_core_thread(bot_main, runtime)
        if live is not None:
            return (_register_real_core(bot_main, runtime, live, "restart_race_existing"), "restart_race_existing")
        engine = importlib.import_module("bot.nija_core_loop")
        starter = getattr(engine, "start_trading_engine", None)
        if not callable(starter):
            return False, "start_trading_engine_unavailable"
        thread = starter(strategy)
        deadline = time.time() + 5.0
        while not _thread_alive(thread) and time.time() < deadline:
            time.sleep(0.05)
        if not _thread_alive(thread):
            os.environ["NIJA_CORE_THREAD_ALIVE"] = "0"
            return False, "restarted_core_not_alive"
        if not _register_real_core(bot_main, runtime, thread, "canonical_strategy_restart"):
            return False, "restarted_core_registration_failed"
        LOGGER.critical(
            "WRITER_V81_CORE_THREAD_RESTARTED marker=%s strategy=%s thread=%s ident=%s",
            MARKER,
            type(strategy).__name__,
            getattr(thread, "name", "unknown"),
            getattr(thread, "ident", None),
        )
        return True, "canonical_strategy_restart"
    except Exception as exc:
        os.environ["NIJA_CORE_THREAD_ALIVE"] = "0"
        LOGGER.error(
            "WRITER_V81_CORE_THREAD_RESTART_FAILED marker=%s error=%s:%s",
            MARKER,
            type(exc).__name__,
            exc,
        )
        return False, f"restart_error:{type(exc).__name__}:{exc}"
    finally:
        _RESTART_LOCK.release()


def _patch_runtime_authority_probe() -> bool:
    try:
        module = importlib.import_module("bot.runtime_authority_convergence_repair_patch")
    except Exception:
        return False
    current = getattr(module, "_heartbeat_ready", None)
    if not callable(current) or getattr(current, _PATCH_ATTR, False):
        return bool(callable(current))

    @wraps(current)
    def heartbeat_ready_v81():
        # Synchronize NIJA_CORE_THREAD_ALIVE from a real thread before the legacy
        # convergence probe reads the env-only core-thread gate.
        repair_core_thread_once()
        return current()

    setattr(heartbeat_ready_v81, _PATCH_ATTR, True)
    setattr(heartbeat_ready_v81, "__wrapped__", current)
    module._heartbeat_ready = heartbeat_ready_v81
    LOGGER.critical("WRITER_V81_AUTHORITY_PROBE_PATCHED marker=%s", MARKER)
    return True


def reconcile_once() -> dict[str, Any]:
    with _LOCK:
        predicates = _patch_recovery_predicates()
        authority_probe = _patch_runtime_authority_probe()
        core_ok, core_reason = repair_core_thread_once()
        return {
            "predicates": predicates,
            "authority_probe": authority_probe,
            "core_ok": core_ok,
            "core_reason": core_reason,
        }


def _watchdog() -> None:
    try:
        interval = max(2.0, _f(os.environ.get("NIJA_WRITER_V81_POLL_S"), 5.0))
    except Exception:
        interval = 5.0
    last = ""
    while not _STOP.wait(interval):
        try:
            state = reconcile_once()
            signature = f"{state.get('core_ok')}:{state.get('core_reason')}"
            if signature != last:
                log = LOGGER.info if state.get("core_ok") else LOGGER.warning
                log(
                    "WRITER_V81_STATE marker=%s core_ok=%s core_reason=%s epoch_reason=%s",
                    MARKER,
                    str(bool(state.get("core_ok"))).lower(),
                    state.get("core_reason"),
                    os.environ.get("NIJA_WRITER_RECOVERY_EPOCH_REASON", ""),
                )
                last = signature
        except Exception as exc:
            LOGGER.warning("WRITER_V81_WATCHDOG_ERROR marker=%s error=%s:%s", MARKER, type(exc).__name__, exc)


def install_import_hook() -> bool:
    global _STARTED
    with _LOCK:
        _patch_recovery_predicates()
        _patch_runtime_authority_probe()
        if not _STARTED:
            _STARTED = True
            threading.Thread(target=_watchdog, name="WriterRecoveryEpochCoreV81", daemon=True).start()
        os.environ["NIJA_WRITER_RECOVERY_EPOCH_CORE_V81_INSTALLED"] = "1"
    LOGGER.critical(
        "WRITER_RECOVERY_EPOCH_CORE_V81_INSTALLED marker=%s bounded_epoch=true real_core_only=true canonical_restart=true fail_closed=true",
        MARKER,
    )
    return True


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "recoverable_reason",
    "repair_core_thread_once",
    "reconcile_once",
    "_secondary_is_same_epoch",
]
