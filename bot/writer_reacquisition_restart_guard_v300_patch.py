"""Writer reacquisition stale-restart guard v300.

Production on 2026-08-30 exposed a process-lifecycle race in
``EntrypointWriterAuthority``.  Generation 5008 lost exact Redis ownership and
correctly scheduled the existing 15 second callback-free fallback restart.  The
same process then reacquired exact Redis writer authority as generation 5009
before that timer expired.  The old timer was not cancelled and its callback
unconditionally called ``os._exit(75)``, killing the recovered writer and
leaving its freshly reacquired Redis lease behind until TTL expiry.

v300 does not relax writer fencing or manufacture authority.  It only makes a
restart timer belong to the loss epoch that created it:

* successful distributed reacquisition cancels and invalidates any older loss
  timer;
* each timer captures its loss epoch, generation and token;
* the timer callback self-suppresses if it has been superseded or if the same
  runtime has genuinely reacquired and still exactly owns its current Redis
  lock;
* a runtime that remains genuinely lost still exits with code 75 exactly as
  before.

Redis acquisition/release scripts, fencing-token generation, nonce policy,
broker registration, readiness, capital, position, risk, kill-switch, order and
fill gates are unchanged.  No lock is force released, no writer authority is
granted and no readiness proof is fabricated.
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

LOGGER = logging.getLogger("nija.writer_reacquisition_restart_guard_v300")
MARKER = "20260830-writer-reacquisition-restart-guard-v300"
_READY_FLAG = "NIJA_WRITER_REACQUISITION_RESTART_GUARD_V300_READY"
_IMPORT_HOOK_FLAG = "_NIJA_WRITER_REACQUISITION_RESTART_GUARD_V300_IMPORT_HOOK"
_PATCH_ATTR = "_nija_writer_reacquisition_restart_guard_v300"
_GUARD = threading.RLock()


def _text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value or "")


def _timer_alive(timer: Any) -> bool:
    if timer is None:
        return False
    reader = getattr(timer, "is_alive", None)
    if not callable(reader):
        return False
    try:
        return bool(reader())
    except Exception:
        return False


def _result_acquired(runtime: Any) -> bool:
    result = getattr(runtime, "_result", None)
    return bool(result is not None and getattr(result, "acquired", False))


def _exact_current_redis_owner(runtime: Any) -> tuple[bool, str]:
    """Read-only exact ownership verification for restart suppression.

    A Redis read failure never suppresses the fallback restart.  This keeps the
    timer fail-closed when current distributed ownership cannot be proven.
    """
    client = getattr(runtime, "_client", None)
    lock_key = str(getattr(runtime, "_lock_key", "") or "")
    lock_value = str(getattr(runtime, "_lock_value", "") or "")
    if client is None or not lock_key or not lock_value:
        return False, "exact_redis_proof_unavailable"
    try:
        current = _text(client.get(lock_key))
    except Exception as exc:
        return False, f"redis_read_failed:{type(exc).__name__}:{exc}"
    if not current:
        return False, "redis_lock_missing"
    if current != lock_value:
        return False, "redis_lock_owner_mismatch"
    return True, "exact_redis_process_writer"


def _next_epoch(runtime: Any) -> int:
    try:
        current = int(getattr(runtime, "_nija_v300_restart_epoch", 0) or 0)
    except Exception:
        current = 0
    current += 1
    setattr(runtime, "_nija_v300_restart_epoch", current)
    return current


def _cancel_pending_restart(
    runtime: Any,
    *,
    reason: str,
    new_generation: int | None = None,
    new_token: str | None = None,
) -> bool:
    """Invalidate and cancel the currently pending loss timer, if any."""
    with _GUARD:
        timer = getattr(runtime, "_unhandled_loss_restart_timer", None)
        old_epoch = int(getattr(runtime, "_nija_v300_restart_epoch", 0) or 0)
        old_generation = int(
            getattr(runtime, "_nija_v300_restart_generation", 0) or 0
        )
        _next_epoch(runtime)  # invalidates callbacks even if Timer.cancel races
        setattr(runtime, "_unhandled_loss_restart_timer", None)
        setattr(runtime, "_nija_v300_restart_generation", 0)
        setattr(runtime, "_nija_v300_restart_token", "")
        setattr(runtime, "_nija_v300_restart_callback", None)

    if timer is not None:
        cancel = getattr(timer, "cancel", None)
        if callable(cancel):
            try:
                cancel()
            except Exception:
                pass
        LOGGER.critical(
            "ENTRYPOINT_WRITER_AUTHORITY_FALLBACK_RESTART_CANCELLED marker=%s "
            "reason=%s old_epoch=%d old_generation=%d new_generation=%s "
            "new_token_prefix=%s timer_was_alive=%s authority_granted=false "
            "redis_mutated=false safety_gates_bypassed=false",
            MARKER,
            reason,
            old_epoch,
            old_generation,
            str(new_generation if new_generation is not None else getattr(runtime, "_generation", 0)),
            str(new_token if new_token is not None else getattr(runtime, "_token", ""))[:8],
            str(_timer_alive(timer)).lower(),
        )
        return True
    return False


def _restart_suppression_reason(
    runtime: Any,
    *,
    timer: Any,
    epoch: int,
    scheduled_generation: int,
    scheduled_token: str,
) -> tuple[bool, str]:
    """Return whether a timer callback is stale and must not terminate process."""
    with _GUARD:
        current_timer = getattr(runtime, "_unhandled_loss_restart_timer", None)
        current_epoch = int(getattr(runtime, "_nija_v300_restart_epoch", 0) or 0)
    if current_timer is not timer:
        return True, "timer_superseded"
    if current_epoch != epoch:
        return True, "loss_epoch_superseded"

    lost = getattr(runtime, "_lost", None)
    try:
        lost_now = bool(lost.is_set()) if lost is not None else True
    except Exception:
        lost_now = True
    current_generation = int(getattr(runtime, "_generation", 0) or 0)
    current_token = str(getattr(runtime, "_token", "") or "")
    local_recovered = bool(
        not lost_now
        and _result_acquired(runtime)
        and (
            current_generation != scheduled_generation
            or current_token != scheduled_token
        )
    )
    if not local_recovered:
        return False, "loss_still_current"

    exact, exact_detail = _exact_current_redis_owner(runtime)
    if exact:
        return True, f"writer_recovered:{exact_detail}"
    return False, f"recovery_not_exact:{exact_detail}"


def _schedule_restart_v300(
    runtime: Any,
    owner_module: ModuleType,
    reason: str,
    *,
    handler_confirmed: bool = False,
) -> None:
    live_mode = getattr(owner_module, "_live_mode", None)
    try:
        live = bool(live_mode()) if callable(live_mode) else False
    except Exception:
        live = False
    if not live or handler_confirmed:
        return

    heartbeat = getattr(runtime, "_heartbeat_thread", None)
    if heartbeat is None or not _timer_alive(heartbeat):
        return

    with _GUARD:
        existing = getattr(runtime, "_unhandled_loss_restart_timer", None)
        if _timer_alive(existing):
            return

        cfg_float = getattr(owner_module, "_cfg_float", None)
        if callable(cfg_float):
            grace_s = cfg_float(
                "NIJA_WRITER_AUTHORITY_FALLBACK_RESTART_GRACE_S",
                cfg_float(
                    "NIJA_WRITER_AUTHORITY_RESTART_GRACE_S",
                    cfg_float(
                        "NIJA_CORE_REGISTRATION_RESTART_GRACE_S",
                        15.0,
                        minimum=1.0,
                    ),
                    minimum=1.0,
                ),
                minimum=1.0,
            )
        else:
            grace_s = 15.0

        epoch = _next_epoch(runtime)
        scheduled_generation = int(getattr(runtime, "_generation", 0) or 0)
        scheduled_token = str(getattr(runtime, "_token", "") or "")
        setattr(runtime, "_nija_v300_restart_generation", scheduled_generation)
        setattr(runtime, "_nija_v300_restart_token", scheduled_token)

        timer: threading.Timer

        def _force_restart() -> None:
            suppress, detail = _restart_suppression_reason(
                runtime,
                timer=timer,
                epoch=epoch,
                scheduled_generation=scheduled_generation,
                scheduled_token=scheduled_token,
            )
            if suppress:
                with _GUARD:
                    if getattr(runtime, "_unhandled_loss_restart_timer", None) is timer:
                        setattr(runtime, "_unhandled_loss_restart_timer", None)
                        setattr(runtime, "_nija_v300_restart_callback", None)
                LOGGER.critical(
                    "ENTRYPOINT_WRITER_AUTHORITY_FALLBACK_RESTART_SUPPRESSED marker=%s "
                    "reason=%s scheduled_reason=%s epoch=%d scheduled_generation=%d "
                    "current_generation=%s authority_granted=false redis_mutated=false "
                    "safety_gates_bypassed=false",
                    MARKER,
                    detail,
                    reason,
                    epoch,
                    scheduled_generation,
                    str(getattr(runtime, "_generation", 0)),
                )
                return

            logger = getattr(owner_module, "logger", LOGGER)
            base_marker = str(getattr(owner_module, "_MARKER", "unknown"))
            logger.critical(
                "ENTRYPOINT_WRITER_AUTHORITY_FALLBACK_RESTART marker=%s "
                "reason=%s exit_code=75 callback_handoff_confirmed=false "
                "v300_guard=true loss_epoch=%d scheduled_generation=%d "
                "current_generation=%s suppression_detail=%s",
                base_marker,
                reason,
                epoch,
                scheduled_generation,
                str(getattr(runtime, "_generation", 0)),
                detail,
            )
            for handler in logging.getLogger().handlers:
                try:
                    handler.flush()
                except Exception:
                    pass
            os._exit(75)

        timer = threading.Timer(float(grace_s), _force_restart)
        timer.name = "entrypoint-writer-unhandled-loss-restart-v300"
        timer.daemon = True
        setattr(runtime, "_unhandled_loss_restart_timer", timer)
        setattr(runtime, "_nija_v300_restart_callback", _force_restart)

    logger = getattr(owner_module, "logger", LOGGER)
    base_marker = str(getattr(owner_module, "_MARKER", "unknown"))
    logger.critical(
        "ENTRYPOINT_WRITER_AUTHORITY_FALLBACK_RESTART_SCHEDULED marker=%s "
        "reason=%s grace_s=%.1f callback_handoff_confirmed=false "
        "v300_guard=true loss_epoch=%d scheduled_generation=%d",
        base_marker,
        reason,
        float(grace_s),
        epoch,
        scheduled_generation,
    )
    timer.start()


def _patch(module: ModuleType) -> bool:
    cls = getattr(module, "EntrypointWriterAuthority", None)
    if not isinstance(cls, type):
        return False
    if bool(getattr(cls, _PATCH_ATTR, False)):
        return True

    original_activate = getattr(cls, "_activate_distributed_authority", None)
    original_schedule = getattr(cls, "_schedule_unhandled_loss_restart", None)
    if not callable(original_activate) or not callable(original_schedule):
        return False

    @wraps(original_activate)
    def activate_v300(self: Any, *args: Any, **kwargs: Any) -> Any:
        result = original_activate(self, *args, **kwargs)
        if bool(getattr(result, "acquired", False)) and not bool(
            getattr(result, "local_fallback", False)
        ):
            _cancel_pending_restart(
                self,
                reason="writer_reacquired",
                new_generation=int(getattr(result, "generation", 0) or 0),
                new_token=str(getattr(result, "token", "") or ""),
            )
        return result

    @wraps(original_schedule)
    def schedule_v300(
        self: Any,
        reason: str,
        *,
        handler_confirmed: bool = False,
    ) -> None:
        return _schedule_restart_v300(
            self,
            module,
            reason,
            handler_confirmed=handler_confirmed,
        )

    cls._activate_distributed_authority = activate_v300
    cls._schedule_unhandled_loss_restart = schedule_v300
    setattr(cls, _PATCH_ATTR, True)
    return True


def _patch_loaded() -> bool:
    found = False
    for name in ("bot.entrypoint_writer_authority", "entrypoint_writer_authority"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            found = _patch(module) or found
    return found


def install_import_hook() -> bool:
    patched = _patch_loaded()
    if not bool(getattr(builtins, _IMPORT_HOOK_FLAG, False)):
        original_import = builtins.__import__

        @wraps(original_import)
        def importing(name, globals=None, locals=None, fromlist=(), level=0):
            result = original_import(name, globals, locals, fromlist, level)
            if str(name).endswith("entrypoint_writer_authority"):
                _patch_loaded()
            return result

        builtins.__import__ = importing
        setattr(builtins, _IMPORT_HOOK_FLAG, True)

    os.environ[_READY_FLAG] = "1"
    LOGGER.critical(
        "WRITER_REACQUISITION_RESTART_GUARD_V300_READY marker=%s ready=true "
        "loaded_authority_patched=%s stale_loss_timer_cancel_on_reacquire=true "
        "loss_epoch_bound=true exact_redis_recovery_recheck=true genuine_loss_restart_preserved=true "
        "writer_authority_granted=false redis_mutated=false fencing_unchanged=true "
        "nonce_risk_capital_position_killswitch_order_fill_gates_unchanged=true "
        "forced_activation=false safety_gates_bypassed=false",
        MARKER,
        str(patched).lower(),
    )
    return True


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "_patch",
    "_patch_loaded",
    "_cancel_pending_restart",
    "_restart_suppression_reason",
    "_schedule_restart_v300",
]
