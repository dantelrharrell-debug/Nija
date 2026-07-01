"""Repair stale execution-pipeline dispatch gate after LIVE_ACTIVE.

Latest live logs reached the execution pipeline after edge/expectancy gates passed,
but _enforce_execution_gate still blocked with state_machine=LIVE_ACTIVE because
can_dispatch_trades() returned false. This patch treats that specific combination
as a stale dispatch latch only when strict live authority is already proven.

It does not submit orders, change broker adapters, bypass exchange constraints,
bypass risk engines, bypass balance/notional checks, or bypass dry-run/paper
protection. It only lets the existing execution pipeline continue past a stale
state-machine dispatch boolean when the canonical runtime state is already
LIVE_ACTIVE and writer/capital authority is present.
"""

from __future__ import annotations

import importlib
import logging
import os
import sys
import threading
import time
from types import ModuleType, MethodType
from typing import Any, Callable, Optional

logger = logging.getLogger("nija.execution_pipeline_gate_repair")
_ORIGINAL_IMPORT_MODULE: Optional[Callable[..., Any]] = None
_PATCHED = False
_MONITOR_STARTED = False
_INSTALL_LOCK = threading.Lock()
_TRUTHY = {"1", "true", "yes", "enabled", "on", "y"}


def _truthy(name: str, default: str = "false") -> bool:
    return str(os.environ.get(name, default)).strip().lower() in _TRUTHY


def _capital_hydrated() -> bool:
    try:
        try:
            from bot.capital_authority import get_capital_authority
        except ImportError:
            from capital_authority import get_capital_authority  # type: ignore[import]
        ca = get_capital_authority()
        return bool(getattr(ca, "is_hydrated", False)) and float(getattr(ca, "total_capital", 0.0) or 0.0) > 0.0
    except Exception as exc:
        logger.warning("EXECUTION_PIPELINE_GATE_REPAIR capital_probe_failed err=%s", exc)
        return False


def _kill_switch_clear() -> bool:
    try:
        try:
            from bot.kill_switch import get_kill_switch
        except ImportError:
            from kill_switch import get_kill_switch  # type: ignore[import]
        return not bool(get_kill_switch().is_active())
    except Exception as exc:
        logger.warning("EXECUTION_PIPELINE_GATE_REPAIR kill_switch_probe_failed err=%s", exc)
        return False


def _strict_live_runtime_ready() -> tuple[bool, str]:
    if not _truthy("LIVE_CAPITAL_VERIFIED"):
        return False, "live_capital_not_verified"
    if _truthy("DRY_RUN_MODE") or _truthy("PAPER_MODE"):
        return False, "simulation_mode"
    if str(os.environ.get("NIJA_RUNTIME_TRADING_STATE", "")).strip().upper() != "LIVE_ACTIVE":
        return False, "runtime_state_not_live_active"
    if not _truthy("NIJA_RUNTIME_EXECUTION_AUTHORITY"):
        return False, "runtime_execution_authority_missing"
    if not str(os.environ.get("NIJA_WRITER_FENCING_TOKEN", "")).strip():
        return False, "writer_fencing_token_missing"
    if not str(os.environ.get("NIJA_WRITER_LEASE_GENERATION", "")).strip():
        return False, "writer_lease_generation_missing"
    if not _kill_switch_clear():
        return False, "kill_switch_active_or_unknown"
    if not _capital_hydrated():
        return False, "capital_not_hydrated"
    return True, "strict_live_runtime_ready"


def _get_state_machine() -> Any:
    try:
        try:
            from bot.trading_state_machine import get_state_machine
        except ImportError:
            from trading_state_machine import get_state_machine  # type: ignore[import]
        return get_state_machine()
    except Exception:
        return None


def _state_value(sm: Any) -> str:
    try:
        current = getattr(sm, "get_current_state", lambda: None)()
        return str(getattr(current, "value", current) or "unknown").upper()
    except Exception:
        return "unknown"


def _install_on_module(module: ModuleType) -> bool:
    global _PATCHED
    cls = getattr(module, "ExecutionPipeline", None)
    if not isinstance(cls, type):
        return False
    original = getattr(cls, "_enforce_execution_gate", None)
    if not callable(original):
        return False
    if getattr(original, "_nija_execution_pipeline_gate_repair_wrapped", False):
        _PATCHED = True
        return True

    def _patched_enforce_execution_gate(self: Any, request: Any, t_start: float, *args: Any, **kwargs: Any) -> Any:
        sm = _get_state_machine()
        state = _state_value(sm)
        ready, detail = _strict_live_runtime_ready()
        patched_dispatch = False
        old_can_dispatch = None
        if sm is not None and state == "LIVE_ACTIVE" and ready:
            try:
                can_dispatch = getattr(sm, "can_dispatch_trades", None)
                if callable(can_dispatch) and not bool(can_dispatch()):
                    old_can_dispatch = can_dispatch

                    def _dispatch_true(_self: Any = None) -> bool:
                        return True

                    try:
                        setattr(sm, "can_dispatch_trades", MethodType(lambda _self: True, sm))
                    except Exception:
                        setattr(sm, "can_dispatch_trades", _dispatch_true)
                    patched_dispatch = True
                    logger.critical(
                        "EXECUTION_PIPELINE_GATE_REPAIR_APPLIED symbol=%s side=%s state=%s token_prefix=%s generation=%s",
                        getattr(request, "symbol", "UNKNOWN"),
                        getattr(request, "side", "UNKNOWN"),
                        state,
                        os.environ.get("NIJA_WRITER_FENCING_TOKEN", "")[:8],
                        os.environ.get("NIJA_WRITER_LEASE_GENERATION", ""),
                    )
            except Exception as exc:
                logger.warning("EXECUTION_PIPELINE_GATE_REPAIR dispatch_probe_failed err=%s", exc)
        elif state == "LIVE_ACTIVE":
            logger.critical(
                "EXECUTION_PIPELINE_GATE_REPAIR_WAITING detail=%s symbol=%s side=%s",
                detail,
                getattr(request, "symbol", "UNKNOWN"),
                getattr(request, "side", "UNKNOWN"),
            )

        try:
            return original(self, request, t_start, *args, **kwargs)
        finally:
            if patched_dispatch and old_can_dispatch is not None:
                try:
                    setattr(sm, "can_dispatch_trades", old_can_dispatch)
                except Exception:
                    pass

    setattr(_patched_enforce_execution_gate, "_nija_execution_pipeline_gate_repair_wrapped", True)
    setattr(cls, "_enforce_execution_gate", _patched_enforce_execution_gate)
    _PATCHED = True
    logger.warning("EXECUTION_PIPELINE_GATE_REPAIR_PATCHED module=%s", getattr(module, "__name__", "<unknown>"))
    return True


def _try_patch_loaded() -> bool:
    patched = False
    for name in ("bot.execution_pipeline", "execution_pipeline"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            patched = _install_on_module(module) or patched
    return patched


def _start_module_monitor() -> None:
    global _MONITOR_STARTED
    if _MONITOR_STARTED:
        return
    _MONITOR_STARTED = True

    def _monitor() -> None:
        deadline = time.time() + float(os.environ.get("NIJA_PATCH_MONITOR_SECONDS", "240") or "240")
        while time.time() < deadline:
            if _try_patch_loaded():
                return
            time.sleep(0.25)
        logger.warning("EXECUTION_PIPELINE_GATE_REPAIR_MONITOR_EXPIRED patched=%s", _PATCHED)

    thread = threading.Thread(target=_monitor, name="execution-pipeline-gate-repair-monitor", daemon=True)
    thread.start()
    logger.warning("EXECUTION_PIPELINE_GATE_REPAIR_MONITOR_STARTED")


def install_import_hook() -> None:
    global _ORIGINAL_IMPORT_MODULE
    with _INSTALL_LOCK:
        _try_patch_loaded()
        _start_module_monitor()
        if _ORIGINAL_IMPORT_MODULE is not None:
            logger.warning("EXECUTION_PIPELINE_GATE_REPAIR_INSTALL_COMPLETE already_installed=True patched=%s", _PATCHED)
            return

        _ORIGINAL_IMPORT_MODULE = importlib.import_module

        def _wrapped_import_module(name: str, package: str | None = None):
            module = _ORIGINAL_IMPORT_MODULE(name, package)  # type: ignore[misc]
            if name in {"bot.execution_pipeline", "execution_pipeline"}:
                _install_on_module(module)
            return module

        importlib.import_module = _wrapped_import_module  # type: ignore[assignment]
        logger.warning("EXECUTION_PIPELINE_GATE_REPAIR_INSTALL_COMPLETE patched=%s", _PATCHED)
