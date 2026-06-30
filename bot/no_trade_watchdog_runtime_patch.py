"""No-trade watchdog diagnostics for live NIJA deployments.

When startup is healthy and the market scanner is running but no fills occur,
operators need to know whether NIJA is simply waiting for a valid setup or if a
hidden gate is blocking the signal -> execution path.  This runtime patch adds
cycle-level watchdog telemetry without changing trade admission rules.
"""

from __future__ import annotations

import builtins
import logging
import os
import time
from functools import wraps
from typing import Any

logger = logging.getLogger("nija.no_trade_watchdog")
_PATCHED_ATTR = "__nija_no_trade_watchdog_patch__"

_STATE = {
    "cycle_count": 0,
    "execute_attempts": 0,
    "execute_successes": 0,
    "last_execute_ts": 0.0,
    "last_cycle_ts": 0.0,
}


def _truthy(name: str, default: bool = True) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on", "y", "enabled"}


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _int_env(name: str, default: int) -> int:
    try:
        return int(float(os.environ.get(name, default)))
    except (TypeError, ValueError):
        return default


def _risk_snapshot() -> dict[str, Any]:
    keys = (
        "NIJA_MAX_TOTAL_EXPOSURE_PCT",
        "NIJA_MAX_POSITION_SIZE_PCT",
        "MAX_POSITION_PCT",
        "NIJA_DAILY_LOSS_LIMIT_PCT",
        "DAILY_LOSS_LIMIT_PCT",
        "MAX_OPEN_POSITIONS",
        "NIJA_MAX_OPEN_POSITIONS",
        "MIN_TRADE_USD",
        "MIN_NOTIONAL_OVERRIDE",
        "KRAKEN_MIN_NOTIONAL_USD",
        "COINBASE_MIN_ORDER_USD",
        "OKX_MIN_ORDER_USD",
        "HF_MIN_CONFIDENCE",
        "HF_MIN_ADX",
        "HF_MIN_VOLUME_PCT",
    )
    return {key: os.environ.get(key) for key in keys if os.environ.get(key) is not None}


def _log_watchdog(label: str, *, force: bool = False) -> None:
    if not _truthy("NIJA_NO_TRADE_WATCHDOG_ENABLED", True):
        return
    interval = max(1, _int_env("NIJA_NO_TRADE_WATCHDOG_INTERVAL", 10))
    cycles = int(_STATE["cycle_count"])
    if not force and cycles % interval != 0:
        return
    now = time.time()
    since_exec = None if not _STATE["last_execute_ts"] else max(0.0, now - float(_STATE["last_execute_ts"]))
    logger.warning(
        "NO_TRADE_WATCHDOG label=%s cycles=%d execute_attempts=%d execute_successes=%d seconds_since_execute=%s risk_config=%s",
        label,
        cycles,
        int(_STATE["execute_attempts"]),
        int(_STATE["execute_successes"]),
        "never" if since_exec is None else f"{since_exec:.1f}",
        _risk_snapshot(),
    )


def _wrap_cycle_method(cls: type, method_name: str) -> None:
    original = getattr(cls, method_name, None)
    if not callable(original) or getattr(original, _PATCHED_ATTR, False):
        return

    @wraps(original)
    def _wrapped(self: Any, *args: Any, **kwargs: Any):
        _STATE["cycle_count"] = int(_STATE["cycle_count"]) + 1
        _STATE["last_cycle_ts"] = time.time()
        try:
            result = original(self, *args, **kwargs)
            _log_watchdog(f"{cls.__name__}.{method_name}")
            return result
        except Exception as exc:
            logger.exception("NO_TRADE_WATCHDOG_CYCLE_EXCEPTION label=%s.%s error=%s", cls.__name__, method_name, exc)
            raise

    setattr(_wrapped, _PATCHED_ATTR, True)
    setattr(cls, method_name, _wrapped)
    logger.warning("NO_TRADE_WATCHDOG_CYCLE_WIRED class=%s method=%s", cls.__name__, method_name)


def _wrap_execute_action(cls: type) -> None:
    original = getattr(cls, "execute_action", None)
    if not callable(original) or getattr(original, _PATCHED_ATTR, False):
        return

    @wraps(original)
    def _wrapped(self: Any, analysis: Any, symbol: str, *args: Any, **kwargs: Any):
        _STATE["execute_attempts"] = int(_STATE["execute_attempts"]) + 1
        _STATE["last_execute_ts"] = time.time()
        try:
            logger.warning(
                "NO_TRADE_WATCHDOG_EXECUTE_ATTEMPT symbol=%s action=%s score=%s size=%s",
                symbol,
                analysis.get("action") if isinstance(analysis, dict) else None,
                analysis.get("score") if isinstance(analysis, dict) else None,
                analysis.get("position_size") if isinstance(analysis, dict) else None,
            )
        except Exception:
            logger.warning("NO_TRADE_WATCHDOG_EXECUTE_ATTEMPT symbol=%s", symbol)
        result = original(self, analysis, symbol, *args, **kwargs)
        if result:
            _STATE["execute_successes"] = int(_STATE["execute_successes"]) + 1
            logger.warning("NO_TRADE_WATCHDOG_EXECUTE_SUCCESS symbol=%s", symbol)
        else:
            logger.warning("NO_TRADE_WATCHDOG_EXECUTE_RETURNED_FALSE symbol=%s", symbol)
        return result

    setattr(_wrapped, _PATCHED_ATTR, True)
    setattr(cls, "execute_action", _wrapped)
    logger.warning("NO_TRADE_WATCHDOG_EXECUTE_WIRED class=%s", cls.__name__)


def _patch_module(module: Any) -> bool:
    if module is None:
        return False
    patched = False
    try:
        core_cls = getattr(module, "NijaCoreLoop", None)
        if isinstance(core_cls, type):
            for method_name in ("run_cycle", "run_scan_phase", "_phase3_scan_and_enter"):
                _wrap_cycle_method(core_cls, method_name)
                patched = True
    except Exception as exc:
        logger.debug("no-trade core patch skipped: %s", exc)
    try:
        strategy_cls = getattr(module, "TradingStrategy", None)
        if isinstance(strategy_cls, type):
            _wrap_cycle_method(strategy_cls, "run_cycle")
            patched = True
    except Exception as exc:
        logger.debug("no-trade strategy patch skipped: %s", exc)
    try:
        apex_cls = getattr(module, "NIJAApexStrategyV71", None)
        if isinstance(apex_cls, type):
            _wrap_execute_action(apex_cls)
            patched = True
    except Exception as exc:
        logger.debug("no-trade apex patch skipped: %s", exc)
    return patched


def install_import_hook() -> None:
    import sys

    for name, module in list(sys.modules.items()):
        if name.endswith(("nija_core_loop", "trading_strategy", "nija_apex_strategy_v71")):
            _patch_module(module)

    if getattr(builtins, "_NIJA_NO_TRADE_WATCHDOG_HOOK_INSTALLED", False):
        return

    original_import = builtins.__import__

    def guarded_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
        module = original_import(name, globals, locals, fromlist, level)
        if name.endswith(("nija_core_loop", "trading_strategy", "nija_apex_strategy_v71")):
            try:
                _patch_module(module)
            except Exception as exc:
                logger.warning("No-trade watchdog patch failed for %s: %s", name, exc)
        return module

    builtins.__import__ = guarded_import
    setattr(builtins, "_NIJA_NO_TRADE_WATCHDOG_HOOK_INSTALLED", True)
    logger.warning("NO_TRADE_WATCHDOG_INSTALL_COMPLETE")
