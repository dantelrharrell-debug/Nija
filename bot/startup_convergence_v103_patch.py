"""Bound startup convergence without weakening live-trading safety gates.

Production deployment 28200b7b on 2026-08-15 exposed two independent startup
failure modes:

1. canonical TradingStrategy recovery v102 remained safely passive but its
   12-second observation window expired while the real module was still
   ``__spec__._initializing=True``;
2. runtime_execution_convergence_v32 re-entered its own capital reconciliation
   path through refresh callbacks, producing RecursionError during both periodic
   convergence and writer-acquired reconciliation.

v103 addresses only those convergence mechanics:
* extend the passive class-observation default to 45 seconds while preserving an
  explicit NIJA_STRATEGY_CLASS_RECOVERY_TIMEOUT_S override;
* wrap v32 runtime reconciliation in a process-local non-blocking single-flight
  guard so nested refresh callbacks are coalesced instead of recursively entered;
* preserve every existing readiness, capital, writer/nonce, risk, broker,
  position, and execution gate. No readiness state is synthesized.
"""
from __future__ import annotations

import logging
import os
import threading
from functools import wraps
from typing import Any, Callable

LOGGER = logging.getLogger("nija.startup_convergence_v103")
MARKER = "20260815-startup-convergence-v103"
_DEFAULT_STRATEGY_TIMEOUT_S = 45.0
_LOCK = threading.RLock()
_RECONCILE_GUARD = threading.Lock()
_INSTALLED = False


def _strategy_timeout_s() -> float:
    raw = os.environ.get("NIJA_STRATEGY_CLASS_RECOVERY_TIMEOUT_S")
    if raw is None or not str(raw).strip():
        return _DEFAULT_STRATEGY_TIMEOUT_S
    try:
        return max(0.1, float(raw))
    except (TypeError, ValueError):
        return _DEFAULT_STRATEGY_TIMEOUT_S


def _patch_v102_timeout() -> bool:
    try:
        from bot import canonical_strategy_class_recovery_v102_patch as v102
    except ImportError:
        import canonical_strategy_class_recovery_v102_patch as v102  # type: ignore[import]

    setattr(v102, "_timeout_s", _strategy_timeout_s)
    LOGGER.critical(
        "STARTUP_CONVERGENCE_V103_STRATEGY_TIMEOUT marker=%s default_timeout_s=%.1f "
        "explicit_env_override_preserved=true passive_observer_unchanged=true",
        MARKER,
        _DEFAULT_STRATEGY_TIMEOUT_S,
    )
    return True


def _patch_v32_reconciliation() -> bool:
    try:
        from bot import runtime_execution_convergence_v32 as v32
    except ImportError:
        import runtime_execution_convergence_v32 as v32  # type: ignore[import]

    current = getattr(v32, "_request_runtime_reconciliation", None)
    if not callable(current):
        return False
    if getattr(current, "_nija_startup_convergence_v103", False):
        return True

    @wraps(current)
    def single_flight(trigger: str, *args: Any, **kwargs: Any) -> bool:
        if not _RECONCILE_GUARD.acquire(blocking=False):
            LOGGER.warning(
                "STARTUP_CONVERGENCE_V103_RECONCILE_COALESCED marker=%s trigger=%s "
                "nested_refresh_skipped=true fail_closed=true",
                MARKER,
                trigger,
            )
            return False
        try:
            return bool(current(trigger, *args, **kwargs))
        finally:
            _RECONCILE_GUARD.release()

    setattr(single_flight, "_nija_startup_convergence_v103", True)
    setattr(single_flight, "__wrapped__", current)
    setattr(v32, "_request_runtime_reconciliation", single_flight)
    LOGGER.critical(
        "STARTUP_CONVERGENCE_V103_RECONCILE_GUARD marker=%s single_flight=true "
        "nested_refresh_coalesced=true safety_gates_unchanged=true",
        MARKER,
    )
    return True


def install() -> bool:
    global _INSTALLED
    with _LOCK:
        if _INSTALLED:
            return True
        if not _patch_v102_timeout():
            return False
        if not _patch_v32_reconciliation():
            return False
        os.environ["NIJA_STARTUP_CONVERGENCE_V103_INSTALLED"] = "1"
        _INSTALLED = True
    LOGGER.critical(
        "STARTUP_CONVERGENCE_V103_INSTALLED marker=%s strategy_timeout_s=%.1f "
        "runtime_reconcile_single_flight=true fail_closed=true",
        MARKER,
        _strategy_timeout_s(),
    )
    return True


def install_import_hook() -> bool:
    return install()


__all__ = ["MARKER", "install", "install_import_hook", "_strategy_timeout_s"]
