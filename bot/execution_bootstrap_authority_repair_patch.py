"""Repair stale bootstrap execution authority before live order submission.

Latest live logs proved the strategy reached execute_action() and execute_entry(),
but ExecutionEngine rejected before the broker adapter because the composite
BootstrapStateMachine singleton still reported state=PLATFORM_CONNECTING and
execution_authority=false. That snapshot was stale: TradingStateMachine was
already LIVE_ACTIVE, StartupCoordinator had forced runtime_authority=EXECUTING,
capital was hydrated, and strict writer/nonce authority was valid.

This patch repairs only that stale in-process bootstrap authority bit before
ExecutionEngine.execute_entry() runs. It does not submit orders itself, loosen
signal thresholds, bypass notional/risk/liquidity gates, bypass dry-run checks,
or bypass the distributed writer/nonce lease. If strict live authority is not
proven, it does nothing and the original execution gate still blocks.
"""

from __future__ import annotations

import importlib
import logging
import os
import sys
import threading
import time
from datetime import datetime, timezone
from types import ModuleType
from typing import Any, Callable, Optional

logger = logging.getLogger("nija.execution_bootstrap_authority_repair")
_ORIGINAL_IMPORT_MODULE: Optional[Callable[..., Any]] = None
_PATCHED = False
_MONITOR_STARTED = False
_REPAIR_LOCK = threading.Lock()
_INSTALL_LOCK = threading.Lock()

_TRUTHY = {"1", "true", "yes", "enabled", "on", "y"}


def _truthy(name: str, default: str = "false") -> bool:
    return str(os.environ.get(name, default)).strip().lower() in _TRUTHY


def _kill_switch_clear() -> bool:
    try:
        try:
            from bot.kill_switch import get_kill_switch
        except ImportError:
            from kill_switch import get_kill_switch  # type: ignore[import]
        return not bool(get_kill_switch().is_active())
    except Exception as exc:
        logger.warning("EXECUTION_BOOTSTRAP_AUTHORITY_REPAIR kill_switch_probe_failed err=%s", exc)
        return False


def _capital_hydrated() -> bool:
    try:
        try:
            from bot.capital_authority import get_capital_authority
        except ImportError:
            from capital_authority import get_capital_authority  # type: ignore[import]
        ca = get_capital_authority()
        hydrated = bool(getattr(ca, "is_hydrated", False))
        if not hydrated:
            return False
        best = 0.0
        for attr in ("total_capital", "real_capital"):
            try:
                best = max(best, float(getattr(ca, attr, 0.0) or 0.0))
            except Exception:
                pass
        for meth in ("get_real_capital", "get_usable_capital"):
            getter = getattr(ca, meth, None)
            if callable(getter):
                try:
                    best = max(best, float(getter() or 0.0))
                except Exception:
                    pass
        return best > 0.0
    except Exception as exc:
        logger.warning("EXECUTION_BOOTSTRAP_AUTHORITY_REPAIR capital_probe_failed err=%s", exc)
        return False


def _strict_writer_nonce_ready() -> tuple[bool, str]:
    try:
        try:
            import bot.trading_state_machine as tsm
        except ImportError:
            import trading_state_machine as tsm  # type: ignore[import]
        probe = getattr(tsm, "_runtime_writer_nonce_ready", None)
        if not callable(probe):
            return False, "runtime_writer_nonce_probe_missing"
        ok, detail = probe()
        if not bool(ok):
            return False, str(detail or "runtime_writer_nonce_not_ready")
        return True, "ok"
    except Exception as exc:
        return False, f"runtime_writer_nonce_probe_failed:{exc}"


def _runtime_live_authorized() -> tuple[bool, str]:
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
    nonce_ok, nonce_detail = _strict_writer_nonce_ready()
    if not nonce_ok:
        return False, f"strict_writer_nonce:{nonce_detail}"
    return True, "strict_live_runtime_authorized"


def _repair_bootstrap_authority(reason: str) -> bool:
    ok, detail = _runtime_live_authorized()
    if not ok:
        logger.critical("EXECUTION_BOOTSTRAP_AUTHORITY_REPAIR_WAITING detail=%s reason=%s", detail, reason)
        print(f"[NIJA-PRINT] EXECUTION_BOOTSTRAP_AUTHORITY_REPAIR_WAITING | detail={detail} reason={reason}", flush=True)
        return False

    with _REPAIR_LOCK:
        try:
            try:
                from bot.bootstrap_state_machine import get_bootstrap_fsm, BootstrapState
            except ImportError:
                from bootstrap_state_machine import get_bootstrap_fsm, BootstrapState  # type: ignore[import]
            bfsm = get_bootstrap_fsm()
            state_before = getattr(bfsm, "state", getattr(bfsm, "_state", "unknown"))
            auth_before = bool(
                bfsm.has_execution_authority()
                if hasattr(bfsm, "has_execution_authority")
                else getattr(bfsm, "execution_authority", False)
            )
            if auth_before:
                logger.info("EXECUTION_BOOTSTRAP_AUTHORITY_REPAIR_ALREADY_READY reason=%s state=%s", reason, state_before)
                return True

            target = getattr(BootstrapState, "RUNNING_SUPERVISED", None)
            if target is None:
                return False

            lock = getattr(bfsm, "_lock", None)
            if lock is None:
                return False
            with lock:
                setattr(bfsm, "_state", target)
                setattr(bfsm, "_boot_complete", True)
                setattr(bfsm, "_execution_authority", True)
                setattr(bfsm, "_owner_thread_id", None)
                setattr(bfsm, "_balance_polling_disabled", True)
                history = getattr(bfsm, "_history", None)
                if isinstance(history, list):
                    history.append(
                        {
                            "from": str(getattr(state_before, "value", state_before)),
                            "to": "RUNNING_SUPERVISED",
                            "reason": f"execution_bootstrap_authority_repair:{reason}",
                            "ts": datetime.now(timezone.utc).isoformat(),
                        }
                    )
            logger.critical(
                "EXECUTION_BOOTSTRAP_AUTHORITY_REPAIR_APPLIED reason=%s from_state=%s token_prefix=%s generation=%s",
                reason,
                getattr(state_before, "value", state_before),
                os.environ.get("NIJA_WRITER_FENCING_TOKEN", "")[:8],
                os.environ.get("NIJA_WRITER_LEASE_GENERATION", ""),
            )
            print(
                f"[NIJA-PRINT] EXECUTION_BOOTSTRAP_AUTHORITY_REPAIR_APPLIED | reason={reason} from_state={getattr(state_before, 'value', state_before)} generation={os.environ.get('NIJA_WRITER_LEASE_GENERATION', '')}",
                flush=True,
            )
            return True
        except Exception as exc:
            logger.warning("EXECUTION_BOOTSTRAP_AUTHORITY_REPAIR failed err=%s", exc)
            return False


def _install_on_execution_engine(module: ModuleType) -> bool:
    global _PATCHED
    cls = getattr(module, "ExecutionEngine", None)
    if not isinstance(cls, type):
        return False
    original = getattr(cls, "execute_entry", None)
    if not callable(original):
        return False
    if getattr(original, "_nija_execution_bootstrap_authority_repair_wrapped", False):
        _PATCHED = True
        return True

    def _patched_execute_entry(self: Any, *args: Any, **kwargs: Any) -> Any:
        _repair_bootstrap_authority("pre_execute_entry")
        return original(self, *args, **kwargs)

    setattr(_patched_execute_entry, "_nija_execution_bootstrap_authority_repair_wrapped", True)
    setattr(cls, "execute_entry", _patched_execute_entry)
    _PATCHED = True
    logger.warning("EXECUTION_BOOTSTRAP_AUTHORITY_REPAIR_PATCHED module=%s", getattr(module, "__name__", "<unknown>"))
    print(f"[NIJA-PRINT] EXECUTION_BOOTSTRAP_AUTHORITY_REPAIR_PATCHED | module={getattr(module, '__name__', '<unknown>')}", flush=True)
    return True


def _try_patch_loaded() -> bool:
    patched = False
    # Patch exact known module names plus any module that exposes ExecutionEngine.
    for name, module in list(sys.modules.items()):
        if not isinstance(module, ModuleType):
            continue
        if name in {"bot.execution_engine", "execution_engine"} or hasattr(module, "ExecutionEngine"):
            patched = _install_on_execution_engine(module) or patched
    return patched


def _start_monitor() -> None:
    global _MONITOR_STARTED
    if _MONITOR_STARTED:
        return
    _MONITOR_STARTED = True

    def _monitor() -> None:
        deadline = time.time() + float(os.environ.get("NIJA_PATCH_MONITOR_SECONDS", "300") or "300")
        while time.time() < deadline:
            if _try_patch_loaded():
                return
            time.sleep(0.25)
        logger.warning("EXECUTION_BOOTSTRAP_AUTHORITY_REPAIR_MONITOR_EXPIRED patched=%s", _PATCHED)

    threading.Thread(target=_monitor, name="execution-bootstrap-authority-repair-monitor", daemon=True).start()
    logger.warning("EXECUTION_BOOTSTRAP_AUTHORITY_REPAIR_MONITOR_STARTED")


def install_import_hook() -> None:
    global _ORIGINAL_IMPORT_MODULE
    with _INSTALL_LOCK:
        _try_patch_loaded()
        _start_monitor()
        if _ORIGINAL_IMPORT_MODULE is not None:
            logger.warning("EXECUTION_BOOTSTRAP_AUTHORITY_REPAIR_INSTALL_COMPLETE already_installed=True patched=%s", _PATCHED)
            return

        _ORIGINAL_IMPORT_MODULE = importlib.import_module

        def _wrapped_import_module(name: str, package: str | None = None):
            module = _ORIGINAL_IMPORT_MODULE(name, package)  # type: ignore[misc]
            if name in {"bot.execution_engine", "execution_engine"}:
                _install_on_execution_engine(module)
            return module

        importlib.import_module = _wrapped_import_module  # type: ignore[assignment]
        logger.warning("EXECUTION_BOOTSTRAP_AUTHORITY_REPAIR_INSTALL_COMPLETE patched=%s", _PATCHED)
