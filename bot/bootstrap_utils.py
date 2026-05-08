"""Bootstrap helper utilities."""

from __future__ import annotations

import importlib
import logging
import threading
from typing import Callable, Optional

logger = logging.getLogger("nija.bootstrap_utils")
_SHUTDOWN_EVENT = threading.Event()


def resolve_bootstrap_balance_probe() -> Optional[Callable[[], bool]]:
    """Return a callable that reports balance hydration, or None when unavailable."""
    for module_name in ("bot.bootstrap_state_machine", "bootstrap_state_machine"):
        try:
            module = importlib.import_module(module_name)
        except ImportError:
            continue
        probe = getattr(module, "is_bootstrap_balance_hydrated", None)
        if callable(probe):
            return probe
    return None


def dump_startup_state(context: str = "") -> None:
    """Emit a best-effort startup state snapshot for timeout diagnostics."""
    snapshot = {}

    module = None
    for module_name in ("bot.bootstrap_state_machine", "bootstrap_state_machine"):
        try:
            module = importlib.import_module(module_name)
            break
        except ImportError:
            continue
    if module is not None:
        try:
            _bfsm = getattr(module, "get_bootstrap_fsm", lambda: None)()
            snapshot["bootstrap_state"] = getattr(getattr(_bfsm, "state", None), "value", None)
            snapshot["execution_authority"] = bool(getattr(_bfsm, "execution_authority", False))
        except Exception as exc:
            snapshot["bootstrap_state_error"] = str(exc)

    module = None
    for module_name in ("bot.capital_authority", "capital_authority"):
        try:
            module = importlib.import_module(module_name)
            break
        except ImportError:
            continue
    if module is not None:
        try:
            _ca = getattr(module, "get_capital_authority", lambda: None)()
            snapshot["capital_state"] = getattr(getattr(_ca, "state", None), "value", None)
            snapshot["capital_hydrated"] = bool(getattr(_ca, "is_hydrated", False))
            snapshot["capital_ready"] = bool(getattr(_ca, "is_ready", lambda: False)())
        except Exception as exc:
            snapshot["capital_state_error"] = str(exc)

    module = None
    for module_name in ("bot.startup_readiness_gate", "startup_readiness_gate"):
        try:
            module = importlib.import_module(module_name)
            break
        except ImportError:
            continue
    if module is not None:
        try:
            _gate = getattr(module, "get_startup_readiness_gate", lambda: None)()
            snapshot["readiness_gate"] = (
                _gate.get_status() if _gate is not None and hasattr(_gate, "get_status") else None
            )
        except Exception as exc:
            snapshot["readiness_gate_error"] = str(exc)

    module = None
    for module_name in ("bot.nija_core_loop", "nija_core_loop"):
        try:
            module = importlib.import_module(module_name)
            break
        except ImportError:
            continue
    if module is not None:
        try:
            _ready = getattr(module, "TRADING_ENGINE_READY", None)
            snapshot["trading_engine_ready"] = bool(_ready.is_set()) if _ready is not None else None
        except Exception as exc:
            snapshot["trading_engine_ready_error"] = str(exc)

    suffix = f" ({context})" if context else ""
    logger.critical("STARTUP_STATE_DUMP%s: %s", suffix, snapshot)


def get_shutdown_event() -> threading.Event:
    """Return the process-wide shutdown event for bootstrap loops."""
    return _SHUTDOWN_EVENT


def signal_shutdown() -> None:
    """Mark the process-wide shutdown event as set."""
    _SHUTDOWN_EVENT.set()
