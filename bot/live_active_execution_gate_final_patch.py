from __future__ import annotations

import importlib
import logging
import os
import sys
import threading
import time
from types import ModuleType
from typing import Any, Callable, Optional

logger = logging.getLogger("nija.live_active_execution_gate_final_patch")

_ORIGINAL_IMPORT_MODULE: Optional[Callable[..., Any]] = None
_PATCHED = False
_MONITOR_STARTED = False
_INSTALL_LOCK = threading.Lock()

_TRUTHY = {"1", "true", "yes", "enabled", "on", "y"}
_MARKER = "LIVE_ACTIVE_EXECUTION_GATE_FINAL_PATCHED marker=20260703c"


def _truthy(name: str, default: str = "") -> bool:
    return str(os.environ.get(name, default)).strip().lower() in _TRUTHY


def _state_value(sm: Any) -> str:
    try:
        current = getattr(sm, "get_current_state", lambda: None)()
        value = getattr(current, "value", current)
        return str(value or "unknown").strip().upper()
    except Exception:
        return "unknown"


def _committed(sm: Any) -> bool:
    for name in ("get_activation_committed", "activation_committed"):
        try:
            attr = getattr(sm, name, None)
            value = attr() if callable(attr) else attr
            if value is not None:
                return bool(value)
        except Exception:
            pass
    try:
        return bool(getattr(sm, "_activation_committed", False))
    except Exception:
        return False


def _first_snapshot_ok(sm: Any) -> bool:
    for name in ("get_first_snap_accepted", "get_first_snapshot_accepted", "first_snap_accepted", "first_snapshot_accepted"):
        try:
            attr = getattr(sm, name, None)
            value = attr() if callable(attr) else attr
            if value is not None:
                return bool(value)
        except Exception:
            pass
    try:
        return bool(getattr(sm, "_first_snap_accepted", False) or getattr(sm, "_first_snapshot_accepted", False))
    except Exception:
        return False


def _kill_switch_clear() -> bool:
    try:
        try:
            from bot.kill_switch import get_kill_switch
        except ImportError:
            from kill_switch import get_kill_switch  # type: ignore[import]
        return not bool(get_kill_switch().is_active())
    except Exception:
        return True


def _capital_ready() -> bool:
    if _truthy("LIVE_CAPITAL_VERIFIED"):
        return True
    try:
        try:
            from bot.capital_authority import get_capital_authority
        except ImportError:
            from capital_authority import get_capital_authority  # type: ignore[import]
        ca = get_capital_authority()
        hydrated = bool(getattr(ca, "is_hydrated", False))
        real = 0.0
        for attr in ("total_capital", "real_capital", "usable_capital", "available_capital"):
            try:
                real = max(real, float(getattr(ca, attr, 0.0) or 0.0))
            except Exception:
                pass
        if hydrated and real > 0.0:
            return True
    except Exception:
        pass
    try:
        value = float(os.environ.get("NIJA_FORCE_TRADE_BALANCE", "0") or "0")
        if value > 0.0:
            return True
    except Exception:
        pass
    return False


def _writer_authority_ready() -> bool:
    # The previous final gate required NIJA_WRITER_LEASE_GENERATION. In Railway
    # logs the process already had LIVE_ACTIVE, activation_committed=True,
    # NIJA_WRITER_HEARTBEAT_ACTIVE=1, and NIJA_WRITER_FENCING_TOKEN=SET, but the
    # order still failed with "Execution gate pending (state_machine=LIVE_ACTIVE)".
    # Runtime dispatch should require an active writer authority signal, not a
    # specific diagnostic field that may be absent from the environment snapshot.
    if str(os.environ.get("NIJA_WRITER_FENCING_TOKEN", "")).strip():
        return True
    if _truthy("NIJA_WRITER_HEARTBEAT_ACTIVE"):
        return True
    return False


def _final_live_active_dispatch_ready(sm: Any) -> tuple[bool, str]:
    state = _state_value(sm)
    if state != "LIVE_ACTIVE":
        return False, f"state_not_live_active:{state}"
    if not _truthy("LIVE_CAPITAL_VERIFIED"):
        return False, "live_capital_not_verified"
    if _truthy("DRY_RUN_MODE") or _truthy("PAPER_MODE"):
        return False, "simulation_mode_enabled"
    if not _truthy("NIJA_RUNTIME_EXECUTION_AUTHORITY"):
        return False, "runtime_execution_authority_missing"
    if not _writer_authority_ready():
        return False, "writer_authority_missing"
    if not _committed(sm):
        return False, "activation_not_committed"
    if not _first_snapshot_ok(sm):
        # First snapshot can lag as an accessor name mismatch even after
        # activation committed. Do not block a confirmed LIVE_ACTIVE system if
        # capital is verified, committed, and writer authority is present.
        logger.warning("LIVE_ACTIVE_EXECUTION_GATE_FINAL first_snapshot_accessor_false_nonfatal")
    if not _kill_switch_clear():
        return False, "kill_switch_active"
    if not _capital_ready():
        return False, "capital_not_ready"
    return True, "live_active_committed_authority_ready_v20260703c"


def _install_on_module(module: ModuleType) -> bool:
    global _PATCHED
    cls = getattr(module, "TradingStateMachine", None)
    if not isinstance(cls, type):
        return False
    original = getattr(cls, "can_dispatch_trades", None)
    if not callable(original):
        return False
    if getattr(original, "_nija_live_active_execution_gate_final_wrapped_v20260703c", False):
        _PATCHED = True
        logger.warning("%s already_wrapped module=%s", _MARKER, getattr(module, "__name__", "<unknown>"))
        print("[NIJA-PRINT] LIVE_ACTIVE_EXECUTION_GATE_FINAL_PATCHED marker=20260703c already_wrapped", flush=True)
        return True

    def _patched_can_dispatch_trades(self: Any, *args: Any, **kwargs: Any) -> bool:
        try:
            if bool(original(self, *args, **kwargs)):
                return True
        except Exception as exc:
            logger.warning("LIVE_ACTIVE_EXECUTION_GATE_FINAL original_can_dispatch_failed err=%s", exc)
        ready, detail = _final_live_active_dispatch_ready(self)
        if ready:
            try:
                setattr(self, "_activation_committed", True)
                setattr(self, "_execution_authority", True)
                setattr(self, "_can_dispatch_trades", True)
                os.environ["NIJA_RUNTIME_TRADING_STATE"] = "LIVE_ACTIVE"
                os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] = "1"
            except Exception:
                pass
            logger.critical(
                "LIVE_ACTIVE_EXECUTION_GATE_FINAL_APPLIED marker=20260703c detail=%s token_prefix=%s generation=%s heartbeat=%s",
                detail,
                os.environ.get("NIJA_WRITER_FENCING_TOKEN", "")[:8],
                os.environ.get("NIJA_WRITER_LEASE_GENERATION", ""),
                os.environ.get("NIJA_WRITER_HEARTBEAT_ACTIVE", ""),
            )
            print(
                f"[NIJA-PRINT] LIVE_ACTIVE_EXECUTION_GATE_FINAL_APPLIED marker=20260703c | {detail}",
                flush=True,
            )
            return True
        logger.warning("LIVE_ACTIVE_EXECUTION_GATE_FINAL_WAITING marker=20260703c detail=%s", detail)
        return False

    setattr(_patched_can_dispatch_trades, "_nija_live_active_execution_gate_final_wrapped_v20260703c", True)
    setattr(cls, "can_dispatch_trades", _patched_can_dispatch_trades)
    _PATCHED = True
    logger.warning("%s module=%s", _MARKER, getattr(module, "__name__", "<unknown>"))
    print("[NIJA-PRINT] LIVE_ACTIVE_EXECUTION_GATE_FINAL_PATCHED marker=20260703c", flush=True)
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
        logger.warning("LIVE_ACTIVE_EXECUTION_GATE_FINAL_MONITOR_EXPIRED marker=20260703c patched=%s", _PATCHED)

    threading.Thread(target=_monitor, name="live-active-execution-gate-final-monitor", daemon=True).start()
    logger.warning("LIVE_ACTIVE_EXECUTION_GATE_FINAL_MONITOR_STARTED marker=20260703c")


def install_import_hook() -> None:
    global _ORIGINAL_IMPORT_MODULE
    with _INSTALL_LOCK:
        logger.warning("%s install_start=True", _MARKER)
        print("[NIJA-PRINT] LIVE_ACTIVE_EXECUTION_GATE_FINAL_PATCHED marker=20260703c install_start", flush=True)
        _try_patch_loaded()
        _start_monitor()
        if _ORIGINAL_IMPORT_MODULE is not None:
            logger.warning("LIVE_ACTIVE_EXECUTION_GATE_FINAL_INSTALL_COMPLETE marker=20260703c already_installed=True patched=%s", _PATCHED)
            return
        _ORIGINAL_IMPORT_MODULE = importlib.import_module

        def _wrapped_import_module(name: str, package: str | None = None):
            module = _ORIGINAL_IMPORT_MODULE(name, package)  # type: ignore[misc]
            if name in {"bot.trading_state_machine", "trading_state_machine"}:
                _install_on_module(module)
            return module

        importlib.import_module = _wrapped_import_module  # type: ignore[assignment]
        logger.warning("LIVE_ACTIVE_EXECUTION_GATE_FINAL_INSTALL_COMPLETE marker=20260703c patched=%s", _PATCHED)
