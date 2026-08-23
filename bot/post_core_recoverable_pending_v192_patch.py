"""Keep recoverable post-core readiness convergence in the same process (v192).

Production generation 4665 showed a healthy canonical writer/core runtime with
bootstrap RUNNING_SUPERVISED, capital ready, nonce/lease healthy and execution
correctly fail-closed while ``position_sync_ready`` remained pending for Kraken.
The v191 supervised observer intentionally bounded that wait, but on timeout it
requested a process exit.  ``start.sh`` then classified that exit as recoverable
and launched a new Python process, creating a restart cycle around a condition
that already has in-process reconciliation/position-sync recovery.

v192 changes only the liveness handoff.  Once v191 is installed, its 180-second
restart boundary is replaced with a same-process observer.  The observer may
wait indefinitely only while the exact writer remains healthy, the registered
core thread is alive, bootstrap is THREADS_STARTING/RUNNING_SUPERVISED, and no
shutdown has been requested.  Execution authority stays explicitly disabled
until the existing v191 exact execution proof succeeds.  Writer/core loss,
invalid bootstrap state, explicit shutdown, kill-switch/readiness failures and
all existing execution gates remain fail closed and are never fabricated.
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

LOGGER = logging.getLogger("nija.post_core_recoverable_pending_v192")
MARKER = "20260823-post-core-recoverable-pending-v192"
_PATCH_ATTR = "_nija_post_core_recoverable_pending_v192"
_DISPATCH_ATTR = "_nija_post_core_recoverable_pending_v192_dispatch"
_LOCK = threading.RLock()
_INSTALLED = False


def _audit_interval_s() -> float:
    try:
        value = float(os.environ.get("NIJA_POST_CORE_RECOVERABLE_AUDIT_S", "180") or 180.0)
    except (TypeError, ValueError):
        value = 180.0
    return max(30.0, min(900.0, value))


def _bot_main_module() -> ModuleType | None:
    for name in ("bot.bot_main", "bot_main"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            return module
    return None


def _install_on_bot_main(module: ModuleType) -> bool:
    try:
        from bot import position_fetch_generation_v117_patch as v117
    except ImportError:
        import position_fetch_generation_v117_patch as v117  # type: ignore[import]

    current = getattr(module, "_perform_post_core_activation_convergence", None)
    if not callable(current):
        return False
    if getattr(current, _PATCH_ATTR, False):
        return True
    if not getattr(current, "_nija_post_core_execution_handoff_v191", False):
        return False

    base = getattr(current, "__wrapped__", None)
    if not callable(base):
        return False

    @wraps(base)
    def same_process_pending(runtime: Any, trading_thread: Any, *args: Any, **kwargs: Any) -> bool:
        inner_result = bool(base(runtime, trading_thread, *args, **kwargs))
        exact_ready, detail = v117._exact_execution_ready(runtime, trading_thread)
        if exact_ready:
            LOGGER.critical(
                "POST_CORE_RECOVERABLE_PENDING_V192_READY marker=%s inner_result=%s detail=%s "
                "runtime_execution_authority=true trading_gate_may_open=true",
                MARKER,
                str(inner_result).lower(),
                detail,
            )
            return True

        state = v117._bootstrap_state().strip().upper()
        healthy = v117._writer_core_healthy(runtime, trading_thread)
        if (
            v117._shutdown_requested()
            or not healthy
            or state not in {"THREADS_STARTING", "RUNNING_SUPERVISED"}
        ):
            LOGGER.critical(
                "POST_CORE_RECOVERABLE_PENDING_V192_FATAL marker=%s inner_result=%s bootstrap=%s "
                "detail=%s writer_core_healthy=%s shutdown_requested=%s trading_fail_closed=true",
                MARKER,
                str(inner_result).lower(),
                state or "unknown",
                detail,
                str(healthy).lower(),
                str(v117._shutdown_requested()).lower(),
            )
            return False

        os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] = "0"
        os.environ["NIJA_EXECUTION_ACTIVE"] = "false"
        v117._clear_start_gate_while_pending()

        audit_s = _audit_interval_s()
        next_audit = time.monotonic() + audit_s
        attempt = 0
        last_detail = detail
        LOGGER.critical(
            "POST_CORE_RECOVERABLE_PENDING_V192_HOLD marker=%s inner_result=%s bootstrap=%s "
            "detail=%s audit_s=%.1f exact_writer=true core_alive=true "
            "same_process_preserved=true restart_suppressed=true execution_fail_closed=true "
            "trading_gate_opened=false",
            MARKER,
            str(inner_result).lower(),
            state,
            detail,
            audit_s,
        )

        while True:
            if v117._shutdown_requested() or not v117._writer_core_healthy(runtime, trading_thread):
                return False
            state = v117._bootstrap_state().strip().upper()
            if state not in {"THREADS_STARTING", "RUNNING_SUPERVISED"}:
                return False

            v117._request_normal_activation()
            exact_ready, last_detail = v117._exact_execution_ready(runtime, trading_thread)
            if exact_ready:
                LOGGER.critical(
                    "POST_CORE_RECOVERABLE_PENDING_V192_READY marker=%s attempts=%d detail=%s "
                    "same_process_preserved=true runtime_execution_authority=true "
                    "trading_gate_may_open=true",
                    MARKER,
                    attempt + 1,
                    last_detail,
                )
                return True

            attempt += 1
            now = time.monotonic()
            if attempt == 1 or attempt % 10 == 0:
                LOGGER.info(
                    "POST_CORE_RECOVERABLE_PENDING_V192_WAIT marker=%s attempt=%d bootstrap=%s "
                    "detail=%s execution_fail_closed=true restart_suppressed=true",
                    MARKER,
                    attempt,
                    state,
                    last_detail,
                )
            if now >= next_audit:
                LOGGER.warning(
                    "POST_CORE_RECOVERABLE_PENDING_V192_STILL_WAITING marker=%s attempt=%d "
                    "bootstrap=%s detail=%s writer_core_healthy=true "
                    "same_process_preserved=true restart_suppressed=true "
                    "execution_fail_closed=true",
                    MARKER,
                    attempt,
                    state,
                    last_detail,
                )
                next_audit = now + audit_s
            time.sleep(1.0)

    setattr(same_process_pending, _PATCH_ATTR, True)
    # Preserve v117/v191 idempotence so their import hook never wraps v192 again.
    setattr(same_process_pending, getattr(v117, "_PATCH_ATTR", "_nija_position_fetch_generation_v117"), True)
    setattr(same_process_pending, "_nija_post_core_execution_handoff_v191", True)
    setattr(same_process_pending, "__wrapped__", base)
    module._perform_post_core_activation_convergence = same_process_pending
    os.environ["NIJA_POST_CORE_RECOVERABLE_PENDING_V192_READY"] = "1"
    LOGGER.critical(
        "POST_CORE_RECOVERABLE_PENDING_V192_INSTALLED marker=%s "
        "v191_exact_execution_proof_preserved=true recoverable_wait_same_process=true "
        "writer_core_loss_still_terminal=true shutdown_respected=true "
        "runtime_authority_mutated=false trading_state_mutated=false readiness_fabricated=false "
        "position_sync_fabricated=false forced_activation=false safety_gates_bypassed=false",
        MARKER,
    )
    return True


def _patch_v117_dispatch() -> bool:
    try:
        from bot import position_fetch_generation_v117_patch as v117
    except ImportError:
        import position_fetch_generation_v117_patch as v117  # type: ignore[import]

    current = getattr(v117, "_patch_bot_main", None)
    if not callable(current):
        return False
    if getattr(current, _DISPATCH_ATTR, False):
        return bool(current())

    @wraps(current)
    def patch_bot_main_then_v192() -> bool:
        v191_ok = bool(current())
        module = _bot_main_module()
        if module is None:
            return v191_ok
        v192_ok = _install_on_bot_main(module)
        return bool(v191_ok and v192_ok)

    setattr(patch_bot_main_then_v192, _DISPATCH_ATTR, True)
    setattr(patch_bot_main_then_v192, "__wrapped__", current)
    v117._patch_bot_main = patch_bot_main_then_v192
    return bool(patch_bot_main_then_v192())


def install() -> bool:
    global _INSTALLED
    with _LOCK:
        if _INSTALLED:
            module = _bot_main_module()
            return True if module is None else _install_on_bot_main(module)

        try:
            from bot import position_fetch_generation_v117_patch as v117
        except ImportError:
            import position_fetch_generation_v117_patch as v117  # type: ignore[import]

        installer = getattr(v117, "install_import_hook", None) or getattr(v117, "install", None)
        if not callable(installer) or installer() is False:
            return False
        if not _patch_v117_dispatch():
            return False

        os.environ["NIJA_POST_CORE_RECOVERABLE_PENDING_V192_INSTALLED"] = "1"
        _INSTALLED = True
        LOGGER.critical(
            "POST_CORE_RECOVERABLE_PENDING_V192_ARMED marker=%s "
            "v117_import_dispatch_extended=true new_import_hook=false "
            "restart_loop_removed_for_healthy_supervised_pending=true "
            "execution_fail_closed=true safety_gates_bypassed=false",
            MARKER,
        )
        return True


def install_import_hook() -> bool:
    """Compatibility installer name; v192 reuses v117's existing import hook."""
    return install()


__all__ = ["MARKER", "install", "install_import_hook"]
