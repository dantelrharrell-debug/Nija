"""Reassert v192 healthy post-core same-process recovery after late runtime patches.

Production on deployment 9461791975d8f891c1a3a34d8479b7741f0c82f9
reached RUNNING_SUPERVISED with broker, balance, capital, risk, strategy,
bootstrap and position-sync readiness all true, while only the genuine
execution heartbeat proof remained pending.  Despite that healthy state,
bot_main returned false after the finite v172 wait and raised
``Post-core activation convergence failed before dispatch enablement``.  Render
then restarted the process.

That behavior is exactly the restart loop that v192 is intended to suppress.
v205 does not relax the finite v172 inner observation, does not create execution
proof, and does not open the trading gate.  It only reasserts the existing v192
outer same-process hold after the later runtime patch chain has loaded, and
re-extends v117's bot_main patch dispatch so future reassertions cannot silently
lose v192 again.

Execution remains fail closed until the existing canonical readiness, writer,
nonce, kill-switch, risk, capital, reconciliation, order and fill proofs pass.
"""
from __future__ import annotations

import importlib
import logging
import os
import sys
import threading
from functools import wraps
from types import ModuleType
from typing import Any

LOGGER = logging.getLogger("nija.runtime_post_core_recoverable_reassert_v205")
MARKER = "20260823-post-core-recoverable-reassert-v205"
_READY_FLAG = "NIJA_POST_CORE_RECOVERABLE_REASSERT_V205_READY"
_DISPATCH_ATTR = "_nija_post_core_recoverable_reassert_v205_dispatch"
_LOCK = threading.RLock()


def _bot_main_module() -> ModuleType | None:
    for name in ("bot.bot_main", "bot_main"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            return module
    return None


def _v192_guard_present(module: ModuleType | None) -> bool:
    if module is None:
        return False
    current = getattr(module, "_perform_post_core_activation_convergence", None)
    return bool(
        callable(current)
        and getattr(current, "_nija_post_core_recoverable_pending_v192", False)
    )


def _reassert_live_v192(v192: ModuleType) -> bool:
    module = _bot_main_module()
    if module is None:
        return True
    installer = getattr(v192, "_install_on_bot_main", None)
    if not callable(installer):
        return False
    return bool(installer(module)) and _v192_guard_present(module)


def _patch_v117_dispatch(v117: ModuleType, v192: ModuleType) -> bool:
    current = getattr(v117, "_patch_bot_main", None)
    if not callable(current):
        return False
    if getattr(current, _DISPATCH_ATTR, False):
        return bool(current())

    @wraps(current)
    def patch_bot_main_then_v205(*args: Any, **kwargs: Any) -> bool:
        upstream_ok = bool(current(*args, **kwargs))
        live_ok = _reassert_live_v192(v192)
        return bool(upstream_ok and live_ok)

    setattr(patch_bot_main_then_v205, _DISPATCH_ATTR, True)
    setattr(patch_bot_main_then_v205, "__wrapped__", current)
    v117._patch_bot_main = patch_bot_main_then_v205
    return bool(patch_bot_main_then_v205())


def install() -> bool:
    """Restore the existing v192 guard without weakening any execution proof."""
    with _LOCK:
        try:
            v117 = importlib.import_module("bot.position_fetch_generation_v117_patch")
            v192 = importlib.import_module("bot.post_core_recoverable_pending_v192_patch")
        except Exception as exc:
            os.environ[_READY_FLAG] = "0"
            LOGGER.critical(
                "POST_CORE_RECOVERABLE_REASSERT_V205_FAILED marker=%s reason=dependency_import_failed "
                "error=%s:%s trading_fail_closed=true",
                MARKER,
                type(exc).__name__,
                exc,
            )
            return False

        v192_installer = getattr(v192, "install", None) or getattr(v192, "install_import_hook", None)
        v192_armed = bool(callable(v192_installer) and v192_installer() is not False)
        dispatch_ready = _patch_v117_dispatch(v117, v192) if v192_armed else False
        live_ready = _reassert_live_v192(v192) if dispatch_ready else False
        module = _bot_main_module()
        guard_present = _v192_guard_present(module) if module is not None else True

        ready = bool(v192_armed and dispatch_ready and live_ready and guard_present)
        os.environ[_READY_FLAG] = "1" if ready else "0"
        if not ready:
            LOGGER.critical(
                "POST_CORE_RECOVERABLE_REASSERT_V205_FAILED marker=%s v192_armed=%s "
                "dispatch_ready=%s live_ready=%s guard_present=%s trading_fail_closed=true",
                MARKER,
                str(v192_armed).lower(),
                str(dispatch_ready).lower(),
                str(live_ready).lower(),
                str(guard_present).lower(),
            )
            return False

        LOGGER.critical(
            "POST_CORE_RECOVERABLE_REASSERT_V205_READY marker=%s ready=true "
            "v192_live_guard=true v117_dispatch_reasserted=true same_process_recovery=true "
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
    "_v192_guard_present",
    "_reassert_live_v192",
]
