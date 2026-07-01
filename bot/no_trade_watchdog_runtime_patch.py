"""No-trade watchdog diagnostics for live NIJA deployments.

When startup is healthy and the market scanner is running but no fills occur,
operators need to know whether NIJA is simply waiting for a valid setup or if a
hidden gate is blocking the signal -> execution path.  This runtime patch adds
cycle-level watchdog telemetry without changing trade admission rules.
"""

from __future__ import annotations

import builtins
import importlib
import logging
import os
import sys
import threading
import time
from functools import wraps
from typing import Any

logger = logging.getLogger("nija.no_trade_watchdog")
_PATCHED_ATTR = "__nija_no_trade_watchdog_patch__"
_AUTOWIRE_STARTED = False
_AUTOWIRE_LOCK = threading.Lock()
_IMPORT_HOOK_INSTALLED = False
_MONITOR_STARTED = False
_MONITOR_LOCK = threading.Lock()

_STATE = {
    "cycle_count": 0,
    "execute_attempts": 0,
    "execute_successes": 0,
    "last_execute_ts": 0.0,
    "last_cycle_ts": 0.0,
    "patched_classes": set(),
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
        "NIJA_RUNTIME_TRADING_STATE",
        "NIJA_RUNTIME_EXECUTION_AUTHORITY",
        "NIJA_WRITER_FENCING_TOKEN",
        "NIJA_WRITER_LEASE_GENERATION",
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
    since_cycle = None if not _STATE["last_cycle_ts"] else max(0.0, now - float(_STATE["last_cycle_ts"]))
    patched_classes = sorted(str(name) for name in (_STATE.get("patched_classes") or set()))
    logger.warning(
        "NO_TRADE_WATCHDOG label=%s cycles=%d execute_attempts=%d execute_successes=%d seconds_since_cycle=%s seconds_since_execute=%s patched_classes=%s risk_config=%s",
        label,
        cycles,
        int(_STATE["execute_attempts"]),
        int(_STATE["execute_successes"]),
        "never" if since_cycle is None else f"{since_cycle:.1f}",
        "never" if since_exec is None else f"{since_exec:.1f}",
        patched_classes,
        _risk_snapshot(),
    )


def _wrap_cycle_method(cls: type, method_name: str) -> bool:
    original = getattr(cls, method_name, None)
    if not callable(original) or getattr(original, _PATCHED_ATTR, False):
        return False

    @wraps(original)
    def _wrapped(self: Any, *args: Any, **kwargs: Any):
        _STATE["cycle_count"] = int(_STATE["cycle_count"]) + 1
        _STATE["last_cycle_ts"] = time.time()
        try:
            logger.critical(
                "TRADE_LOOP_HEARTBEAT cycle=%d phase=%s.%s_start runtime_state=%s execution_authority=%s",
                int(_STATE["cycle_count"]),
                cls.__name__,
                method_name,
                os.environ.get("NIJA_RUNTIME_TRADING_STATE"),
                os.environ.get("NIJA_RUNTIME_EXECUTION_AUTHORITY"),
            )
            result = original(self, *args, **kwargs)
            logger.critical(
                "TRADE_LOOP_HEARTBEAT cycle=%d phase=%s.%s_complete execute_attempts=%d execute_successes=%d",
                int(_STATE["cycle_count"]),
                cls.__name__,
                method_name,
                int(_STATE["execute_attempts"]),
                int(_STATE["execute_successes"]),
            )
            _log_watchdog(f"{cls.__name__}.{method_name}")
            return result
        except Exception as exc:
            logger.exception("NO_TRADE_WATCHDOG_CYCLE_EXCEPTION label=%s.%s error=%s", cls.__name__, method_name, exc)
            raise

    setattr(_wrapped, _PATCHED_ATTR, True)
    setattr(cls, method_name, _wrapped)
    _STATE.setdefault("patched_classes", set()).add(f"{cls.__name__}.{method_name}")
    logger.warning("NO_TRADE_WATCHDOG_CYCLE_WIRED class=%s method=%s", cls.__name__, method_name)
    return True


def _wrap_execute_action(cls: type) -> bool:
    original = getattr(cls, "execute_action", None)
    if not callable(original) or getattr(original, _PATCHED_ATTR, False):
        return False

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
    _STATE.setdefault("patched_classes", set()).add(f"{cls.__name__}.execute_action")
    logger.warning("NO_TRADE_WATCHDOG_EXECUTE_WIRED class=%s", cls.__name__)
    return True


def _patch_module(module: Any) -> bool:
    if module is None:
        return False
    patched = False
    try:
        core_cls = getattr(module, "NijaCoreLoop", None)
        if isinstance(core_cls, type):
            for method_name in ("run_cycle", "run_scan_phase", "_phase3_scan_and_enter", "start", "run", "main_loop"):
                patched = _wrap_cycle_method(core_cls, method_name) or patched
    except Exception as exc:
        logger.debug("no-trade core patch skipped: %s", exc)
    try:
        strategy_cls = getattr(module, "TradingStrategy", None)
        if isinstance(strategy_cls, type):
            for method_name in ("run_cycle", "scan_market", "scan_markets", "execute_trade_cycle"):
                patched = _wrap_cycle_method(strategy_cls, method_name) or patched
            patched = _wrap_execute_action(strategy_cls) or patched
    except Exception as exc:
        logger.debug("no-trade strategy patch skipped: %s", exc)
    try:
        apex_cls = getattr(module, "NIJAApexStrategyV71", None)
        if isinstance(apex_cls, type):
            for method_name in ("run_cycle", "scan_market", "scan_markets"):
                patched = _wrap_cycle_method(apex_cls, method_name) or patched
            patched = _wrap_execute_action(apex_cls) or patched
    except Exception as exc:
        logger.debug("no-trade apex patch skipped: %s", exc)
    return patched


def _patch_loaded_modules() -> int:
    patched = 0
    for name, module in list(sys.modules.items()):
        if name.endswith(("nija_core_loop", "trading_strategy", "nija_apex_strategy_v71")):
            if _patch_module(module):
                patched += 1
    return patched


def _resolve_and_patch_modules() -> int:
    patched = _patch_loaded_modules()
    for module_name in (
        "bot.nija_core_loop",
        "nija_core_loop",
        "bot.trading_strategy",
        "trading_strategy",
        "bot.nija_apex_strategy_v71",
        "nija_apex_strategy_v71",
    ):
        try:
            module = sys.modules.get(module_name) or importlib.import_module(module_name)
        except Exception as exc:
            logger.debug("NO_TRADE_WATCHDOG import probe skipped module=%s error=%s", module_name, exc)
            continue
        if _patch_module(module):
            patched += 1
    return patched


def _install_autowire_worker() -> None:
    global _AUTOWIRE_STARTED
    if _AUTOWIRE_STARTED:
        return
    with _AUTOWIRE_LOCK:
        if _AUTOWIRE_STARTED:
            return
        _AUTOWIRE_STARTED = True

        def _worker() -> None:
            deadline = time.monotonic() + _float_env("NIJA_NO_TRADE_WATCHDOG_AUTOWIRE_TIMEOUT_S", 180.0)
            logger.warning("NO_TRADE_WATCHDOG_AUTOWIRE started")
            while time.monotonic() < deadline:
                patched = _resolve_and_patch_modules()
                if patched > 0:
                    logger.warning("NO_TRADE_WATCHDOG_AUTOWIRE patched_modules=%d", patched)
                    return
                time.sleep(0.25)
            logger.error("NO_TRADE_WATCHDOG_AUTOWIRE timeout: no core/strategy class was observed or importable")

        threading.Thread(target=_worker, name="no-trade-watchdog-autowire", daemon=True).start()


def _install_live_active_monitor() -> None:
    global _MONITOR_STARTED
    if _MONITOR_STARTED:
        return
    with _MONITOR_LOCK:
        if _MONITOR_STARTED:
            return
        _MONITOR_STARTED = True

        def _monitor() -> None:
            delay = max(30.0, _float_env("NIJA_NO_TRADE_WATCHDOG_LIVE_DELAY_S", 120.0))
            interval = max(15.0, _float_env("NIJA_NO_TRADE_WATCHDOG_LIVE_INTERVAL_S", 60.0))
            next_warn = time.time() + delay
            while True:
                time.sleep(min(5.0, interval))
                runtime_state = os.environ.get("NIJA_RUNTIME_TRADING_STATE", "")
                live_active = runtime_state == "LIVE_ACTIVE" or _truthy("LIVE_CAPITAL_VERIFIED", False)
                if not live_active:
                    continue
                now = time.time()
                if now < next_warn:
                    continue
                if int(_STATE["cycle_count"]) <= 0:
                    logger.critical(
                        "TRADE_LOOP_NOT_OBSERVED live_active=%s cycles=0 patched_classes=%s seconds_after_startup>=%.1f risk_config=%s",
                        runtime_state or "unknown",
                        sorted(str(name) for name in (_STATE.get("patched_classes") or set())),
                        delay,
                        _risk_snapshot(),
                    )
                    _resolve_and_patch_modules()
                else:
                    _log_watchdog("live_active_monitor", force=True)
                next_warn = now + interval

        threading.Thread(target=_monitor, name="no-trade-live-active-monitor", daemon=True).start()
        logger.warning("NO_TRADE_WATCHDOG_LIVE_ACTIVE_MONITOR_STARTED")


def _install_import_hook() -> None:
    global _IMPORT_HOOK_INSTALLED
    if _IMPORT_HOOK_INSTALLED or getattr(builtins, "_NIJA_NO_TRADE_WATCHDOG_HOOK_INSTALLED", False):
        _IMPORT_HOOK_INSTALLED = True
        return
    original_import = builtins.__import__

    def guarded_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
        module = original_import(name, globals, locals, fromlist, level)
        targets = [module]
        child = sys.modules.get(name)
        if child is not None:
            targets.append(child)
        if fromlist:
            base_name = getattr(child or module, "__name__", "")
            for item in fromlist:
                nested = sys.modules.get(f"{base_name}.{item}")
                if nested is not None:
                    targets.append(nested)
                attr = getattr(module, item, None)
                if attr is not None:
                    targets.append(attr)
        for target in targets:
            try:
                mod_name = getattr(target, "__name__", "")
                if mod_name.endswith(("nija_core_loop", "trading_strategy", "nija_apex_strategy_v71")):
                    _patch_module(target)
            except Exception as exc:
                logger.warning("No-trade watchdog patch failed for %s: %s", name, exc)
        return module

    builtins.__import__ = guarded_import
    setattr(builtins, "_NIJA_NO_TRADE_WATCHDOG_HOOK_INSTALLED", True)
    _IMPORT_HOOK_INSTALLED = True


def install_import_hook() -> None:
    if not _truthy("NIJA_NO_TRADE_WATCHDOG_ENABLED", True):
        logger.warning("NO_TRADE_WATCHDOG disabled by NIJA_NO_TRADE_WATCHDOG_ENABLED=false")
        return
    _resolve_and_patch_modules()
    _install_import_hook()
    _install_autowire_worker()
    _install_live_active_monitor()
    logger.warning("NO_TRADE_WATCHDOG_INSTALL_COMPLETE")
