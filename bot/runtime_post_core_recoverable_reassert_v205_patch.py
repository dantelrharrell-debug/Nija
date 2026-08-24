"""Reassert healthy post-core same-process recovery after late runtime patches.

Production on deployment 9461791975d8f891c1a3a34d8479b7741f0c82f9
proved that a healthy RUNNING_SUPERVISED process could still unwind after the
finite v172 wait while the genuine execution heartbeat proof was pending.
Deployment 531a58d371f383cb06913c58e23707f539e9b852 then proved the first v205
implementation was too dependent on the historical v192 wrapper shape:
``v192_armed=false`` made v205 fail before it could restore the guard.

v205 now owns the late outer guard directly.  It preserves the entire current
post-core callable as the inner observation, then keeps the same process alive
only while the exact writer/core remain healthy, bootstrap is
THREADS_STARTING/RUNNING_SUPERVISED, and shutdown has not been requested.  The
existing exact execution proof observer remains authoritative; v205 never sets
readiness, LIVE_ACTIVE, execution authority, capital, nonce, position, order or
fill proof.

The historical v192 marker is retained only as an idempotence compatibility
marker so later v192 replays do not replace this stronger late outer guard.
Execution remains fail closed until all canonical safety gates pass.
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

LOGGER = logging.getLogger("nija.runtime_post_core_recoverable_reassert_v205")
MARKER = "20260823-post-core-recoverable-reassert-v205"
_READY_FLAG = "NIJA_POST_CORE_RECOVERABLE_REASSERT_V205_READY"
_PATCH_ATTR = "_nija_post_core_recoverable_reassert_v205"
_DISPATCH_ATTR = "_nija_post_core_recoverable_reassert_v205_dispatch"
_V192_COMPAT_ATTR = "_nija_post_core_recoverable_pending_v192"
_LOCK = threading.RLock()


def _bot_main_module() -> ModuleType | None:
    for name in ("bot.bot_main", "bot_main"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            return module
    return None


def _audit_interval_s() -> float:
    try:
        value = float(os.environ.get("NIJA_POST_CORE_RECOVERABLE_AUDIT_S", "180") or 180.0)
    except (TypeError, ValueError):
        value = 180.0
    return max(30.0, min(900.0, value))


def _callable_chain_has_attr(target: Any, attr: str) -> bool:
    current = target
    seen: set[int] = set()
    for _ in range(48):
        if not callable(current) or id(current) in seen:
            break
        seen.add(id(current))
        if bool(getattr(current, attr, False)):
            return True
        current = getattr(current, "__wrapped__", None)
    return False


def _guard_present(module: ModuleType | None) -> bool:
    if module is None:
        return False
    current = getattr(module, "_perform_post_core_activation_convergence", None)
    return bool(callable(current) and getattr(current, _PATCH_ATTR, False))


def _required_v117_api(v117: ModuleType) -> bool:
    required = (
        "_patch_bot_main",
        "_exact_execution_ready",
        "_writer_core_healthy",
        "_shutdown_requested",
        "_bootstrap_state",
        "_request_normal_activation",
        "_clear_start_gate_while_pending",
    )
    return all(callable(getattr(v117, name, None)) for name in required)


def _install_outer_guard(v117: ModuleType) -> bool:
    module = _bot_main_module()
    if module is None:
        return True

    current = getattr(module, "_perform_post_core_activation_convergence", None)
    if not callable(current):
        return False
    if getattr(current, _PATCH_ATTR, False):
        return True

    previous = current

    @wraps(previous)
    def same_process_pending(runtime: Any, trading_thread: Any, *args: Any, **kwargs: Any) -> bool:
        inner_result = bool(previous(runtime, trading_thread, *args, **kwargs))
        exact_ready, detail = v117._exact_execution_ready(runtime, trading_thread)
        if exact_ready:
            LOGGER.critical(
                "POST_CORE_RECOVERABLE_REASSERT_V205_EXECUTION_READY marker=%s inner_result=%s "
                "detail=%s runtime_execution_authority=true trading_gate_may_open=true",
                MARKER,
                str(inner_result).lower(),
                detail,
            )
            return True

        state = str(v117._bootstrap_state() or "").strip().upper()
        healthy = bool(v117._writer_core_healthy(runtime, trading_thread))
        shutdown = bool(v117._shutdown_requested())
        if shutdown or not healthy or state not in {"THREADS_STARTING", "RUNNING_SUPERVISED"}:
            LOGGER.critical(
                "POST_CORE_RECOVERABLE_REASSERT_V205_FATAL marker=%s inner_result=%s bootstrap=%s "
                "detail=%s writer_core_healthy=%s shutdown_requested=%s trading_fail_closed=true",
                MARKER,
                str(inner_result).lower(),
                state or "unknown",
                detail,
                str(healthy).lower(),
                str(shutdown).lower(),
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
            "POST_CORE_RECOVERABLE_REASSERT_V205_HOLD marker=%s inner_result=%s bootstrap=%s "
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
            state = str(v117._bootstrap_state() or "").strip().upper()
            if state not in {"THREADS_STARTING", "RUNNING_SUPERVISED"}:
                return False

            v117._request_normal_activation()
            exact_ready, last_detail = v117._exact_execution_ready(runtime, trading_thread)
            if exact_ready:
                LOGGER.critical(
                    "POST_CORE_RECOVERABLE_REASSERT_V205_EXECUTION_READY marker=%s attempts=%d "
                    "detail=%s same_process_preserved=true runtime_execution_authority=true "
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
                    "POST_CORE_RECOVERABLE_REASSERT_V205_WAIT marker=%s attempt=%d bootstrap=%s "
                    "detail=%s execution_fail_closed=true restart_suppressed=true",
                    MARKER,
                    attempt,
                    state,
                    last_detail,
                )
            if now >= next_audit:
                LOGGER.warning(
                    "POST_CORE_RECOVERABLE_REASSERT_V205_STILL_WAITING marker=%s attempt=%d "
                    "bootstrap=%s detail=%s writer_core_healthy=true same_process_preserved=true "
                    "restart_suppressed=true execution_fail_closed=true",
                    MARKER,
                    attempt,
                    state,
                    last_detail,
                )
                next_audit = now + audit_s
            time.sleep(1.0)

    setattr(same_process_pending, _PATCH_ATTR, True)
    # Compatibility only: later v192 replays should recognize that the semantic
    # same-process hold is already present and must not replace this outer guard.
    setattr(same_process_pending, _V192_COMPAT_ATTR, True)
    setattr(same_process_pending, "__wrapped__", previous)
    module._perform_post_core_activation_convergence = same_process_pending
    return _guard_present(module)


def _v117_core_present(v117: ModuleType) -> bool:
    module = _bot_main_module()
    if module is None:
        return True
    target = getattr(module, "_perform_post_core_activation_convergence", None)
    attr = str(getattr(v117, "_PATCH_ATTR", "_nija_position_fetch_generation_v117"))
    return _callable_chain_has_attr(target, attr)


def _patch_v117_dispatch(v117: ModuleType) -> bool:
    current = getattr(v117, "_patch_bot_main", None)
    if not callable(current):
        return False
    if getattr(current, _DISPATCH_ATTR, False):
        try:
            current()
        except Exception:
            pass
        return bool(_v117_core_present(v117) and _install_outer_guard(v117))

    @wraps(current)
    def patch_bot_main_then_v205(*args: Any, **kwargs: Any) -> bool:
        upstream_result = False
        try:
            upstream_result = bool(current(*args, **kwargs))
        except Exception as exc:
            LOGGER.warning(
                "POST_CORE_RECOVERABLE_REASSERT_V205_UPSTREAM_DISPATCH_ERROR marker=%s "
                "error=%s:%s evaluating_live_chain=true",
                MARKER,
                type(exc).__name__,
                exc,
            )
        v117_present = bool(upstream_result or _v117_core_present(v117))
        live_ready = _install_outer_guard(v117)
        return bool(v117_present and live_ready)

    setattr(patch_bot_main_then_v205, _DISPATCH_ATTR, True)
    setattr(patch_bot_main_then_v205, "__wrapped__", current)
    v117._patch_bot_main = patch_bot_main_then_v205
    return bool(patch_bot_main_then_v205())


def install() -> bool:
    """Install a late outer hold independent of the historical v192 wrapper shape."""
    with _LOCK:
        try:
            v117 = importlib.import_module("bot.position_fetch_generation_v117_patch")
        except Exception as exc:
            os.environ[_READY_FLAG] = "0"
            LOGGER.critical(
                "POST_CORE_RECOVERABLE_REASSERT_V205_FAILED marker=%s reason=v117_import_failed "
                "error=%s:%s trading_fail_closed=true",
                MARKER,
                type(exc).__name__,
                exc,
            )
            return False

        api_ready = _required_v117_api(v117)
        dispatch_ready = _patch_v117_dispatch(v117) if api_ready else False
        live_ready = _install_outer_guard(v117) if dispatch_ready else False
        module = _bot_main_module()
        guard_present = _guard_present(module) if module is not None else True
        v117_present = _v117_core_present(v117) if module is not None else True

        ready = bool(api_ready and dispatch_ready and live_ready and guard_present and v117_present)
        os.environ[_READY_FLAG] = "1" if ready else "0"
        if not ready:
            LOGGER.critical(
                "POST_CORE_RECOVERABLE_REASSERT_V205_FAILED marker=%s api_ready=%s dispatch_ready=%s "
                "live_ready=%s guard_present=%s v117_present=%s trading_fail_closed=true",
                MARKER,
                str(api_ready).lower(),
                str(dispatch_ready).lower(),
                str(live_ready).lower(),
                str(guard_present).lower(),
                str(v117_present).lower(),
            )
            return False

        LOGGER.critical(
            "POST_CORE_RECOVERABLE_REASSERT_V205_READY marker=%s ready=true "
            "self_contained_outer_guard=true historical_v192_shape_not_required=true "
            "v117_dispatch_reasserted=true same_process_recovery=true "
            "restart_on_healthy_pending=false execution_authority_granted=false "
            "execution_proof_fabricated=false trading_gate_opened=false forced_activation=false "
            "writer_nonce_risk_killswitch_capital_position_order_fill_gates_unchanged=true "
            "safety_gates_bypassed=false",
            MARKER,
        )
        return True


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "_guard_present",
    "_install_outer_guard",
    "_patch_v117_dispatch",
]
