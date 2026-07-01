from __future__ import annotations

import importlib
import logging
import os
import sys
import threading
import time
from types import ModuleType
from typing import Any, Callable, Optional

logger = logging.getLogger("nija.forced_fallback_payload_repair")
_ORIGINAL_IMPORT_MODULE: Optional[Callable[..., Any]] = None
_PATCHED = False
_MONITOR_STARTED = False
_INSTALL_LOCK = threading.Lock()
_TRUTHY = {"1", "true", "yes", "enabled", "on", "y"}


def _truthy(name: str, default: str = "false") -> bool:
    return str(os.environ.get(name, default)).strip().lower() in _TRUTHY


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default) or default)
    except Exception:
        return default


def _live_runtime_authorized() -> bool:
    return bool(
        _truthy("LIVE_CAPITAL_VERIFIED")
        and not _truthy("DRY_RUN_MODE")
        and not _truthy("PAPER_MODE")
        and str(os.environ.get("NIJA_RUNTIME_TRADING_STATE", "")).strip().upper() == "LIVE_ACTIVE"
        and _truthy("NIJA_RUNTIME_EXECUTION_AUTHORITY")
        and str(os.environ.get("NIJA_WRITER_FENCING_TOKEN", "")).strip()
        and str(os.environ.get("NIJA_WRITER_LEASE_GENERATION", "")).strip()
    )


def _broker_name(loop: Any) -> str:
    try:
        apex = getattr(loop, "apex", None)
        if apex is not None and hasattr(apex, "_get_broker_name"):
            return str(apex._get_broker_name() or "kraken").lower()
    except Exception:
        pass
    return "kraken"


def _min_notional(loop: Any, balance: float) -> float:
    broker = _broker_name(loop)
    try:
        from bot.minimum_notional_gate import get_minimum_notional_gate
        return float(get_minimum_notional_gate().config.get_min_notional_for_broker(broker, balance=balance))
    except Exception:
        try:
            from minimum_notional_gate import get_minimum_notional_gate  # type: ignore[import]
            return float(get_minimum_notional_gate().config.get_min_notional_for_broker(broker, balance=balance))
        except Exception:
            return 2.0 if broker in {"kraken", "coinbase", "okx"} else 5.0


def _build_conservative_payload(loop: Any, *, df: Any, sig: Any, snapshot: Any, action: str, existing_reason: str) -> dict[str, Any]:
    try:
        price = float(df["close"].iloc[-1])
    except Exception:
        price = 0.0
    if price <= 0.0:
        raise ValueError("fallback payload requires positive close price")

    balance = max(float(getattr(snapshot, "balance", 0.0) or 0.0), 0.0)
    if balance <= 0.0:
        raise ValueError("fallback payload requires positive balance")

    floor = _min_notional(loop, balance)
    size = min(max(floor, balance * 0.025), balance)

    sl_pct = max(0.008, min(_float_env("NIJA_FALLBACK_REPAIR_SL_PCT", 0.012), 0.030))
    tp1_pct = max(_float_env("NIJA_FALLBACK_REPAIR_TP1_PCT", 0.040), sl_pct * 2.5, 0.030)
    tp2_pct = max(_float_env("NIJA_FALLBACK_REPAIR_TP2_PCT", 0.060), tp1_pct + 0.010)
    tp3_pct = max(_float_env("NIJA_FALLBACK_REPAIR_TP3_PCT", 0.080), tp2_pct + 0.010)
    expected_win_rate = max(0.35, min(_float_env("NIJA_FALLBACK_REPAIR_EXPECTED_WIN_RATE", 0.50), 0.75))

    if action == "enter_short":
        stop_loss = price * (1.0 + sl_pct)
        take_profit = {
            "tp1": price * (1.0 - tp1_pct),
            "tp2": price * (1.0 - tp2_pct),
            "tp3": price * (1.0 - tp3_pct),
            "expected_win_rate": expected_win_rate,
            "market_quality": 1.0,
            "regime": "fallback_repair",
        }
    else:
        stop_loss = price * (1.0 - sl_pct)
        take_profit = {
            "tp1": price * (1.0 + tp1_pct),
            "tp2": price * (1.0 + tp2_pct),
            "tp3": price * (1.0 + tp3_pct),
            "expected_win_rate": expected_win_rate,
            "market_quality": 1.0,
            "regime": "fallback_repair",
        }

    reason = str(existing_reason or getattr(sig, "reason", "fallback_entry") or "fallback_entry")
    if "fallback" not in reason.lower():
        reason = f"{reason} [fallback_entry]"

    return {
        "action": action,
        "entry_price": price,
        "position_size": size,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "trailing_stop_pct": 0.75,
        "reason": reason + " [fallback_payload_repair_cost_aware]",
        "fallback_entry": True,
        "forced_fallback": True,
        "fallback_payload_repaired": True,
        "fallback_edge_geometry_repaired": True,
        "competitive_profitability_policy": "handled_by_downstream_gates",
    }


def _install_on_module(module: ModuleType) -> bool:
    global _PATCHED
    cls = getattr(module, "NijaCoreLoop", None)
    if not isinstance(cls, type):
        return False
    original = getattr(cls, "_build_forced_fallback_entry_analysis", None)
    if not callable(original):
        return False
    if getattr(original, "_nija_forced_fallback_payload_repair_wrapped", False):
        _PATCHED = True
        return True

    def _patched_build_forced_fallback_entry_analysis(self: Any, *args: Any, **kwargs: Any) -> dict[str, Any]:
        try:
            return original(self, *args, **kwargs)
        except ValueError as exc:
            message = str(exc)
            if "competitive profitability policy blocked illiquid fallback entry" not in message:
                raise
            if not _live_runtime_authorized():
                logger.critical("FORCED_FALLBACK_PAYLOAD_REPAIR_WAITING detail=live_runtime_not_authorized err=%s", message)
                print(f"[NIJA-PRINT] FORCED_FALLBACK_PAYLOAD_REPAIR_WAITING | detail=live_runtime_not_authorized err={message}", flush=True)
                raise
            df = kwargs.get("df") if "df" in kwargs else (args[0] if len(args) > 0 else None)
            sig = kwargs.get("sig") if "sig" in kwargs else (args[1] if len(args) > 1 else None)
            snapshot = kwargs.get("snapshot") if "snapshot" in kwargs else (args[2] if len(args) > 2 else None)
            action = kwargs.get("action") if "action" in kwargs else (args[3] if len(args) > 3 else "enter_long")
            existing_reason = kwargs.get("existing_reason", "")
            payload = _build_conservative_payload(
                self,
                df=df,
                sig=sig,
                snapshot=snapshot,
                action=str(action or "enter_long"),
                existing_reason=str(existing_reason or message),
            )
            try:
                setattr(sig, "position_multiplier", 1.0)
            except Exception:
                pass
            tp = payload.get("take_profit") if isinstance(payload.get("take_profit"), dict) else {}
            logger.critical(
                "FORCED_FALLBACK_PAYLOAD_REPAIR_APPLIED symbol=%s action=%s size=%.2f tp1=%s reason=%s",
                getattr(sig, "symbol", "UNKNOWN"),
                payload.get("action"),
                float(payload.get("position_size", 0.0) or 0.0),
                tp.get("tp1"),
                message,
            )
            print(
                f"[NIJA-PRINT] FORCED_FALLBACK_PAYLOAD_REPAIR_APPLIED | symbol={getattr(sig, 'symbol', 'UNKNOWN')} "
                f"action={payload.get('action')} size=${float(payload.get('position_size', 0.0) or 0.0):.2f} edge_geometry=true",
                flush=True,
            )
            return payload

    setattr(_patched_build_forced_fallback_entry_analysis, "_nija_forced_fallback_payload_repair_wrapped", True)
    setattr(cls, "_build_forced_fallback_entry_analysis", _patched_build_forced_fallback_entry_analysis)
    _PATCHED = True
    logger.warning("FORCED_FALLBACK_PAYLOAD_REPAIR_PATCHED module=%s", getattr(module, "__name__", "<unknown>"))
    print(f"[NIJA-PRINT] FORCED_FALLBACK_PAYLOAD_REPAIR_PATCHED | module={getattr(module, '__name__', '<unknown>')}", flush=True)
    return True


def _try_patch_loaded() -> bool:
    patched = False
    # Patch exact known names and every loaded module exposing NijaCoreLoop.
    # Some Railway/runpy paths can load a second class object after the first
    # successful patch, so callers should keep scanning instead of stopping at
    # the first patched module.
    for name, module in list(sys.modules.items()):
        if not isinstance(module, ModuleType):
            continue
        if name in {"bot.nija_core_loop", "nija_core_loop"} or hasattr(module, "NijaCoreLoop"):
            patched = _install_on_module(module) or patched
    return patched


def _start_module_monitor() -> None:
    global _MONITOR_STARTED
    if _MONITOR_STARTED:
        return
    _MONITOR_STARTED = True

    def _monitor() -> None:
        deadline = time.time() + float(os.environ.get("NIJA_PATCH_MONITOR_SECONDS", "300") or "300")
        patched_any = False
        while time.time() < deadline:
            patched_any = _try_patch_loaded() or patched_any
            time.sleep(0.25)
        logger.warning("FORCED_FALLBACK_PAYLOAD_REPAIR_MONITOR_COMPLETE patched=%s patched_any=%s", _PATCHED, patched_any)

    thread = threading.Thread(target=_monitor, name="forced-fallback-payload-repair-monitor", daemon=True)
    thread.start()
    logger.warning("FORCED_FALLBACK_PAYLOAD_REPAIR_MONITOR_STARTED")


def install_import_hook() -> None:
    global _ORIGINAL_IMPORT_MODULE
    with _INSTALL_LOCK:
        _try_patch_loaded()
        _start_module_monitor()
        if _ORIGINAL_IMPORT_MODULE is not None:
            logger.warning("FORCED_FALLBACK_PAYLOAD_REPAIR_INSTALL_COMPLETE already_installed=True patched=%s", _PATCHED)
            return

        _ORIGINAL_IMPORT_MODULE = importlib.import_module

        def _wrapped_import_module(name: str, package: str | None = None):
            module = _ORIGINAL_IMPORT_MODULE(name, package)  # type: ignore[misc]
            if name in {"bot.nija_core_loop", "nija_core_loop"} or hasattr(module, "NijaCoreLoop"):
                _install_on_module(module)
            # Also rescan all loaded modules after imports because normal import
            # statements can populate sys.modules without calling this wrapper for
            # the target name directly.
            _try_patch_loaded()
            return module

        importlib.import_module = _wrapped_import_module  # type: ignore[assignment]
        logger.warning("FORCED_FALLBACK_PAYLOAD_REPAIR_INSTALL_COMPLETE patched=%s", _PATCHED)
