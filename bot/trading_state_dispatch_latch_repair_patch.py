from __future__ import annotations

import importlib
import logging
import os
import sys
import threading
import time
from types import ModuleType
from typing import Any, Callable, Optional

logger = logging.getLogger("nija.trading_state_dispatch_latch_repair")
_ORIGINAL_IMPORT_MODULE: Optional[Callable[..., Any]] = None
_PATCHED = False
_MONITOR_STARTED = False
_INSTALL_LOCK = threading.Lock()


def _truthy(name: str) -> bool:
    return str(os.environ.get(name, "")).strip().lower() in {"1", "true", "yes", "enabled", "on", "y"}


def _current_state_value(sm: Any) -> str:
    try:
        cur = getattr(sm, "get_current_state", lambda: None)()
        return str(getattr(cur, "value", cur) or "unknown").upper()
    except Exception:
        return "unknown"


def _kill_switch_clear() -> bool:
    try:
        try:
            from bot.kill_switch import get_kill_switch
        except ImportError:
            from kill_switch import get_kill_switch  # type: ignore[import]
        return not bool(get_kill_switch().is_active())
    except Exception:
        return True


def _capital_ready() -> tuple[bool, str]:
    try:
        try:
            from bot.capital_authority import get_capital_authority
        except ImportError:
            from capital_authority import get_capital_authority  # type: ignore[import]
        ca = get_capital_authority()
        hydrated = bool(getattr(ca, "is_hydrated", False))
        first_snap = bool(getattr(ca, "first_snap_accepted", False))
        valid_brokers = int(getattr(ca, "valid_broker_count", 0) or 0)
        real = 0.0
        usable = 0.0
        for attr in ("total_capital", "real_capital"):
            try:
                real = max(real, float(getattr(ca, attr, 0.0) or 0.0))
            except Exception:
                pass
        getter = getattr(ca, "get_real_capital", None)
        if callable(getter):
            try:
                real = max(real, float(getter() or 0.0))
            except Exception:
                pass
        usable_getter = getattr(ca, "get_usable_capital", None)
        if callable(usable_getter):
            try:
                usable = max(usable, float(usable_getter() or 0.0))
            except Exception:
                pass
        fresh = True
        fresh_getter = getattr(ca, "is_fresh", None)
        if callable(fresh_getter):
            try:
                fresh = bool(fresh_getter(ttl_s=180.0))
            except TypeError:
                fresh = bool(fresh_getter())
            except Exception:
                fresh = False
        ok = hydrated and first_snap and valid_brokers > 0 and real > 0.0 and usable > 0.0 and fresh
        return ok, f"hydrated={hydrated} first_snap={first_snap} valid_brokers={valid_brokers} real={real:.2f} usable={usable:.2f} fresh={fresh}"
    except Exception as exc:
        return False, f"capital_probe_failed:{exc}"


def _strict_live_dispatch_ready(sm: Any) -> tuple[bool, str]:
    state = _current_state_value(sm)
    if state != "LIVE_ACTIVE":
        return False, f"state_not_live_active:{state}"
    if not _truthy("LIVE_CAPITAL_VERIFIED"):
        return False, "live_capital_not_verified"
    if _truthy("DRY_RUN_MODE") or _truthy("PAPER_MODE"):
        return False, "simulation_mode"
    if not _truthy("NIJA_RUNTIME_EXECUTION_AUTHORITY"):
        return False, "runtime_execution_authority_missing"
    if not str(os.environ.get("NIJA_WRITER_FENCING_TOKEN", "")).strip():
        return False, "writer_fencing_token_missing"
    if not str(os.environ.get("NIJA_WRITER_LEASE_GENERATION", "")).strip():
        return False, "writer_lease_generation_missing"
    if not _kill_switch_clear():
        return False, "kill_switch_active"
    cap_ok, cap_detail = _capital_ready()
    if not cap_ok:
        return False, cap_detail
    return True, f"strict_live_dispatch_ready state={state} {cap_detail}"


def _install_on_module(module: ModuleType) -> bool:
    global _PATCHED
    cls = getattr(module, "TradingStateMachine", None)
    if not isinstance(cls, type):
        return False
    original = getattr(cls, "can_dispatch_trades", None)
    if not callable(original):
        return False
    if getattr(original, "_nija_trading_state_dispatch_latch_repair_wrapped", False):
        _PATCHED = True
        return True

    def _patched_can_dispatch_trades(self: Any, *args: Any, **kwargs: Any) -> bool:
        try:
            if bool(original(self, *args, **kwargs)):
                return True
        except Exception as exc:
            logger.warning("TRADING_STATE_DISPATCH_LATCH_REPAIR original_can_dispatch_failed err=%s", exc)
        ready, detail = _strict_live_dispatch_ready(self)
        if ready:
            try:
                setattr(self, "_activation_committed", True)
                setattr(self, "_execution_authority", True)
                setattr(self, "_core_loop_owns_execution", False)
                setattr(self, "_can_dispatch_trades", True)
            except Exception:
                pass
            logger.critical(
                "TRADING_STATE_DISPATCH_LATCH_REPAIR_APPLIED detail=%s token_prefix=%s generation=%s",
                detail,
                os.environ.get("NIJA_WRITER_FENCING_TOKEN", "")[:8],
                os.environ.get("NIJA_WRITER_LEASE_GENERATION", ""),
            )
            print(f"[NIJA-PRINT] TRADING_STATE_DISPATCH_LATCH_REPAIR_APPLIED | {detail}", flush=True)
            return True
        logger.critical("TRADING_STATE_DISPATCH_LATCH_REPAIR_WAITING detail=%s", detail)
        return False

    setattr(_patched_can_dispatch_trades, "_nija_trading_state_dispatch_latch_repair_wrapped", True)
    setattr(cls, "can_dispatch_trades", _patched_can_dispatch_trades)
    _PATCHED = True
    logger.warning("TRADING_STATE_DISPATCH_LATCH_REPAIR_PATCHED module=%s", getattr(module, "__name__", "<unknown>"))
    return True


def _try_patch_loaded() -> bool:
    patched = False
    for name in ("bot.trading_state_machine", "trading_state_machine"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            patched = _install_on_module(module) or patched
    return patched


def _start_monitor() -> None:
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
        logger.warning("TRADING_STATE_DISPATCH_LATCH_REPAIR_MONITOR_EXPIRED patched=%s", _PATCHED)

    threading.Thread(target=_monitor, name="trading-state-dispatch-latch-repair-monitor", daemon=True).start()
    logger.warning("TRADING_STATE_DISPATCH_LATCH_REPAIR_MONITOR_STARTED")


def install_import_hook() -> None:
    global _ORIGINAL_IMPORT_MODULE
    with _INSTALL_LOCK:
        _try_patch_loaded()
        _start_monitor()
        if _ORIGINAL_IMPORT_MODULE is not None:
            logger.warning("TRADING_STATE_DISPATCH_LATCH_REPAIR_INSTALL_COMPLETE already_installed=True patched=%s", _PATCHED)
            return
        _ORIGINAL_IMPORT_MODULE = importlib.import_module

        def _wrapped_import_module(name: str, package: str | None = None):
            module = _ORIGINAL_IMPORT_MODULE(name, package)  # type: ignore[misc]
            if name in {"bot.trading_state_machine", "trading_state_machine"}:
                _install_on_module(module)
            return module

        importlib.import_module = _wrapped_import_module  # type: ignore[assignment]
        logger.warning("TRADING_STATE_DISPATCH_LATCH_REPAIR_INSTALL_COMPLETE patched=%s", _PATCHED)
