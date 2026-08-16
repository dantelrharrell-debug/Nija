"""Keep the canonical TradingLoop alive while execution authority converges.

Production deployment 2b43a7d2 proved position-sync and bootstrap convergence,
but the canonical TradingLoop still exited after its bounded
``TRADING_ENGINE_READY`` wait expired. That return was then correctly treated
by writer authority as terminal ``core_thread_dead`` and the process restarted.

v120 preserves the existing bounded wait and every execution gate. It wraps
``run_trading_loop`` so that a return is retried only when all of these are true:

* the canonical Redis process-writer proof is still exact and current;
* BootstrapFSM is THREADS_STARTING or RUNNING_SUPERVISED;
* process shutdown/exit has not been requested;
* runtime execution authority is still explicitly zero; and
* TRADING_ENGINE_READY remains unset (the observed startup-pending return path).

No broker I/O, scan, order, readiness, nonce, capital, position, or execution
authority is fabricated. Structural failures still terminate the core thread.
The patch adds no new global import hook; future nija_core_loop imports are
patched by extending the already-installed v54 lifecycle dispatch function.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
import time
from functools import wraps
from types import ModuleType
from typing import Any

LOGGER = logging.getLogger("nija.core_supervised_pending_v120")
MARKER = "20260816-core-supervised-pending-v120"
RELEASE_ID = "20260816-runtime-convergence-v120"
_PATCH_ATTR = "_nija_core_supervised_pending_v120"
_V54_DISPATCH_ATTR = "_nija_core_supervised_pending_v120_dispatch"
_LOCK = threading.RLock()
_INSTALLED = False


def _loaded_core() -> ModuleType | None:
    for name in ("bot.nija_core_loop", "nija_core_loop"):
        mod = sys.modules.get(name)
        if isinstance(mod, ModuleType):
            return mod
    return None


def _shutdown_requested() -> bool:
    if str(os.environ.get("NIJA_PROCESS_EXIT_REQUESTED", "") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return True
    mod = sys.modules.get("bot.bot_main") or sys.modules.get("bot_main")
    shutdown = getattr(mod, "_shutdown_event", None) if isinstance(mod, ModuleType) else None
    return bool(
        shutdown is not None
        and callable(getattr(shutdown, "is_set", None))
        and shutdown.is_set()
    )


def _bootstrap_state() -> str:
    try:
        from bot.bootstrap_state_machine import get_bootstrap_fsm

        fsm = get_bootstrap_fsm()
        state = getattr(fsm, "state", getattr(fsm, "current_state", ""))
        return str(getattr(state, "value", state) or "").strip().upper()
    except Exception:
        return "UNAVAILABLE"


def _writer_proof() -> tuple[bool, str, int]:
    try:
        from bot.writer_runtime_lifecycle_supervisor_v54_patch import _writer_proof as prove

        return prove()
    except Exception as exc:
        return False, f"writer_proof_unavailable:{type(exc).__name__}:{exc}", 0


def _supervised_pending_return_allowed(module: ModuleType) -> tuple[bool, str, int, str]:
    if _shutdown_requested():
        return False, "shutdown_requested", 0, _bootstrap_state()

    ready_event = getattr(module, "TRADING_ENGINE_READY", None)
    if ready_event is None or not callable(getattr(ready_event, "is_set", None)):
        return False, "trading_engine_ready_event_missing", 0, _bootstrap_state()
    if ready_event.is_set():
        return False, "trading_engine_ready_already_set", 0, _bootstrap_state()

    if str(os.environ.get("NIJA_RUNTIME_EXECUTION_AUTHORITY", "0") or "0").strip() == "1":
        return False, "runtime_execution_authority_granted", 0, _bootstrap_state()

    state = _bootstrap_state()
    if state not in {"THREADS_STARTING", "RUNNING_SUPERVISED"}:
        return False, f"bootstrap_state:{state}", 0, state

    ok, reason, generation = _writer_proof()
    if not ok:
        return False, reason, generation, state
    return True, "supervised_activation_pending", generation, state


def _retry_delay_s() -> float:
    try:
        return max(
            0.1,
            min(
                10.0,
                float(os.environ.get("NIJA_CORE_SUPERVISED_PENDING_RETRY_S", "2") or 2.0),
            ),
        )
    except (TypeError, ValueError):
        return 2.0


def _patch_core_loop(module: ModuleType) -> bool:
    current = getattr(module, "run_trading_loop", None)
    if not callable(current):
        return False
    if getattr(current, _PATCH_ATTR, False):
        return True

    @wraps(current)
    def run_trading_loop_v120(strategy: Any, *args: Any, **kwargs: Any) -> None:
        reentries = 0
        while True:
            current(strategy, *args, **kwargs)
            allowed, reason, generation, state = _supervised_pending_return_allowed(module)
            if not allowed:
                if reentries:
                    LOGGER.critical(
                        "CORE_SUPERVISED_PENDING_V120_EXIT marker=%s reentries=%d reason=%s bootstrap=%s generation=%s structural_exit=true",
                        MARKER,
                        reentries,
                        reason,
                        state,
                        generation,
                    )
                return

            reentries += 1
            os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] = "0"
            os.environ["NIJA_EXECUTION_ACTIVE"] = "false"
            LOGGER.critical(
                "CORE_SUPERVISED_PENDING_V120_REENTER marker=%s reentries=%d reason=%s bootstrap=%s generation=%s trading_engine_ready=false broker_io=false execution_fail_closed=true",
                MARKER,
                reentries,
                reason,
                state,
                generation,
            )
            time.sleep(_retry_delay_s())

    setattr(run_trading_loop_v120, _PATCH_ATTR, True)
    setattr(run_trading_loop_v120, "__wrapped__", current)
    module.run_trading_loop = run_trading_loop_v120
    LOGGER.critical(
        "CORE_SUPERVISED_PENDING_V120_PATCHED marker=%s module=%s bounded_wait_preserved=true execution_authority_unchanged=true",
        MARKER,
        module.__name__,
    )
    return True


def _patch_v54_dispatch() -> bool:
    try:
        from bot import writer_runtime_lifecycle_supervisor_v54_patch as v54
    except Exception:
        return False

    current = getattr(v54, "_patch_core_loop", None)
    if not callable(current):
        return False
    if getattr(current, _V54_DISPATCH_ATTR, False):
        return True

    @wraps(current)
    def patch_core_loop_v120(module: ModuleType) -> bool:
        if not current(module):
            return False
        return _patch_core_loop(module)

    setattr(patch_core_loop_v120, _V54_DISPATCH_ATTR, True)
    setattr(patch_core_loop_v120, "__wrapped__", current)
    v54._patch_core_loop = patch_core_loop_v120
    LOGGER.critical(
        "CORE_SUPERVISED_PENDING_V120_V54_DISPATCH_PATCHED marker=%s existing_import_hook_reused=true new_import_hook=false",
        MARKER,
    )
    return True


def _patch_release_manifest() -> bool:
    manifest = sys.modules.get("bot.runtime_release_manifest_patch") or sys.modules.get(
        "runtime_release_manifest_patch"
    )
    if not isinstance(manifest, ModuleType):
        try:
            import bot.runtime_release_manifest_patch as manifest  # type: ignore[no-redef]
        except Exception:
            return False
    required = getattr(manifest, "_REQUIRED_FLAGS", None)
    if not isinstance(required, dict):
        return False
    required["core_supervised_pending_v120"] = "NIJA_CORE_SUPERVISED_PENDING_V120_INSTALLED"
    manifest.RELEASE_ID = RELEASE_ID
    return True


def install() -> bool:
    global _INSTALLED
    with _LOCK:
        if not _patch_v54_dispatch():
            return False

        module = _loaded_core()
        patch_ok = True if module is None else _patch_core_loop(module)
        if not patch_ok:
            return False

        os.environ["NIJA_CORE_SUPERVISED_PENDING_V120_INSTALLED"] = "1"
        if not _patch_release_manifest():
            os.environ.pop("NIJA_CORE_SUPERVISED_PENDING_V120_INSTALLED", None)
            return False

        _INSTALLED = True
        LOGGER.critical(
            "CORE_SUPERVISED_PENDING_V120_INSTALLED marker=%s import_hook_added=false v54_dispatch_reused=true start_gate_timeout_still_bounded=true core_liveness_preserved=true execution_fail_closed=true initial_patch_ready=%s",
            MARKER,
            patch_ok,
        )
        return True


def install_import_hook() -> bool:
    """Compatibility installer name; v120 deliberately installs no import hook."""
    return install()


__all__ = [
    "MARKER",
    "RELEASE_ID",
    "install",
    "install_import_hook",
    "_patch_core_loop",
    "_patch_v54_dispatch",
    "_supervised_pending_return_allowed",
]
