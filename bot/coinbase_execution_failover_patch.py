"""Fail Coinbase live execution over to Kraken when Coinbase is not usable.

Latest live Railway logs showed the strategy and authority gates reaching the
market-order broker pipeline, but the selected execution venue was Coinbase and
Coinbase returned HTTP 403 PERMISSION_DENIED / invalid token. That blocks live
order submission even though Kraken is connected, primary, capital-ready, and
supports the same BTC-USD path.

This patch keeps Coinbase available for balances/market data, but prevents it
from being the final live execution broker by swapping the broker client passed
into ExecutionEngine._submit_market_order_via_pipeline() to the connected
platform Kraken broker when all of the following are true:

- live execution is enabled (not dry-run / paper)
- selected broker client is Coinbase
- failover is enabled (default true)
- a connected Kraken platform broker is available

It does not bypass ECEL, execution authority, risk, notional, balance, or broker
adapter checks. The original pipeline still runs after the broker swap.
"""

from __future__ import annotations

import importlib
import logging
import os
import sys
import threading
import time
from types import ModuleType
from typing import Any, Callable, Optional

logger = logging.getLogger("nija.coinbase_execution_failover")
_ORIGINAL_IMPORT_MODULE: Optional[Callable[..., Any]] = None
_PATCHED = False
_MONITOR_STARTED = False
_INSTALL_LOCK = threading.Lock()
_TRUTHY = {"1", "true", "yes", "enabled", "on", "y"}
_FALSEY = {"0", "false", "no", "disabled", "off", "n"}


def _truthy(name: str, default: str = "false") -> bool:
    return str(os.environ.get(name, default)).strip().lower() in _TRUTHY


def _falsey(name: str, default: str = "false") -> bool:
    return str(os.environ.get(name, default)).strip().lower() in _FALSEY


def _live_mode() -> bool:
    return not _truthy("DRY_RUN_MODE") and not _truthy("PAPER_MODE") and _truthy("LIVE_CAPITAL_VERIFIED", "true")


def _broker_label(broker: Any) -> str:
    try:
        btype = getattr(broker, "broker_type", None)
        if btype is not None:
            return str(getattr(btype, "value", btype) or "").strip().lower()
        name = str(getattr(broker, "NAME", "") or "").strip().lower()
        if name:
            return name
    except Exception:
        pass
    return ""


def _broker_connected(broker: Any) -> bool:
    for attr in ("connected", "is_connected", "_connected"):
        try:
            val = getattr(broker, attr, None)
            if callable(val):
                if bool(val()):
                    return True
            elif val is not None and bool(val):
                return True
        except Exception:
            pass
    return True


def _get_platform_kraken_broker() -> Any:
    try:
        try:
            from bot.multi_account_broker_manager import get_broker_manager
            from bot.broker_manager import BrokerType
        except ImportError:
            from multi_account_broker_manager import get_broker_manager  # type: ignore[import]
            from broker_manager import BrokerType  # type: ignore[import]
        manager = get_broker_manager()
        brokers = getattr(manager, "platform_brokers", None)
        if brokers is None:
            brokers = getattr(manager, "_platform_brokers", None)
        if isinstance(brokers, dict) or hasattr(brokers, "get"):
            broker = brokers.get(BrokerType.KRAKEN) or brokers.get("kraken")
            if broker is not None and _broker_connected(broker):
                return broker
    except Exception as exc:
        logger.debug("Coinbase failover: broker manager lookup failed: %s", exc)

    try:
        try:
            from bot.broker_manager import get_platform_broker, BrokerType
        except ImportError:
            from broker_manager import get_platform_broker, BrokerType  # type: ignore[import]
        broker = get_platform_broker(BrokerType.KRAKEN)
        if broker is not None and _broker_connected(broker):
            return broker
    except Exception as exc:
        logger.debug("Coinbase failover: get_platform_broker lookup failed: %s", exc)

    return None


def _coinbase_failover_enabled() -> bool:
    # Default to enabled because the latest live failure proves Coinbase execution
    # credentials are not usable in Railway. Operators can explicitly disable the
    # failover with NIJA_COINBASE_EXECUTION_FAILOVER_ENABLED=false.
    if _falsey("NIJA_COINBASE_EXECUTION_FAILOVER_ENABLED"):
        return False
    return True


def _should_failover(broker: Any, symbol: str) -> bool:
    if not _live_mode():
        return False
    if not _coinbase_failover_enabled():
        return False
    label = _broker_label(broker)
    if "coinbase" not in label:
        return False
    # Explicitly falsy ENABLE_COINBASE_TRADING also forces failover instead of a
    # dead-end local rejection. With default true, we still fail over because the
    # current Railway Coinbase auth path is returning 403 invalid token.
    if _truthy("NIJA_FORCE_COINBASE_EXECUTION") and not _falsey("ENABLE_COINBASE_TRADING"):
        return False
    return bool(str(symbol or "").strip())


def _install_on_module(module: ModuleType) -> bool:
    global _PATCHED
    cls = getattr(module, "ExecutionEngine", None)
    if not isinstance(cls, type):
        return False
    original = getattr(cls, "_submit_market_order_via_pipeline", None)
    if not callable(original):
        return False
    if getattr(original, "_nija_coinbase_execution_failover_wrapped", False):
        _PATCHED = True
        return True

    def _patched_submit_market_order_via_pipeline(self: Any, broker_client: Any, symbol: str, side: str, size_usd: float, *args: Any, **kwargs: Any) -> Any:
        selected_broker = broker_client
        if _should_failover(broker_client, symbol):
            kraken = _get_platform_kraken_broker()
            if kraken is not None:
                logger.critical(
                    "COINBASE_EXECUTION_FAILOVER_APPLIED symbol=%s side=%s size_usd=%.2f from_broker=coinbase to_broker=kraken reason=coinbase_execution_auth_unusable",
                    symbol,
                    side,
                    float(size_usd or 0.0),
                )
                print(
                    f"[NIJA-PRINT] COINBASE_EXECUTION_FAILOVER_APPLIED | symbol={symbol} side={side} "
                    f"size_usd=${float(size_usd or 0.0):.2f} from_broker=coinbase to_broker=kraken",
                    flush=True,
                )
                selected_broker = kraken
            else:
                logger.critical(
                    "COINBASE_EXECUTION_FAILOVER_UNAVAILABLE symbol=%s side=%s size_usd=%.2f reason=kraken_platform_broker_missing_or_disconnected",
                    symbol,
                    side,
                    float(size_usd or 0.0),
                )
                print(
                    f"[NIJA-PRINT] COINBASE_EXECUTION_FAILOVER_UNAVAILABLE | symbol={symbol} side={side} "
                    f"size_usd=${float(size_usd or 0.0):.2f} reason=kraken_missing",
                    flush=True,
                )
        return original(self, selected_broker, symbol, side, size_usd, *args, **kwargs)

    setattr(_patched_submit_market_order_via_pipeline, "_nija_coinbase_execution_failover_wrapped", True)
    setattr(cls, "_submit_market_order_via_pipeline", _patched_submit_market_order_via_pipeline)
    _PATCHED = True
    logger.warning("COINBASE_EXECUTION_FAILOVER_PATCHED module=%s", getattr(module, "__name__", "<unknown>"))
    print(f"[NIJA-PRINT] COINBASE_EXECUTION_FAILOVER_PATCHED | module={getattr(module, '__name__', '<unknown>')}", flush=True)
    return True


def _try_patch_loaded() -> bool:
    patched = False
    for name, module in list(sys.modules.items()):
        if not isinstance(module, ModuleType):
            continue
        if name in {"bot.execution_engine", "execution_engine"} or hasattr(module, "ExecutionEngine"):
            patched = _install_on_module(module) or patched
    return patched


def _start_monitor() -> None:
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
        logger.warning("COINBASE_EXECUTION_FAILOVER_MONITOR_COMPLETE patched=%s patched_any=%s", _PATCHED, patched_any)

    threading.Thread(target=_monitor, name="coinbase-execution-failover-monitor", daemon=True).start()
    logger.warning("COINBASE_EXECUTION_FAILOVER_MONITOR_STARTED")


def install_import_hook() -> None:
    global _ORIGINAL_IMPORT_MODULE
    with _INSTALL_LOCK:
        _try_patch_loaded()
        _start_monitor()
        if _ORIGINAL_IMPORT_MODULE is not None:
            logger.warning("COINBASE_EXECUTION_FAILOVER_INSTALL_COMPLETE already_installed=True patched=%s", _PATCHED)
            return

        _ORIGINAL_IMPORT_MODULE = importlib.import_module

        def _wrapped_import_module(name: str, package: str | None = None):
            module = _ORIGINAL_IMPORT_MODULE(name, package)  # type: ignore[misc]
            if name in {"bot.execution_engine", "execution_engine"} or hasattr(module, "ExecutionEngine"):
                _install_on_module(module)
            _try_patch_loaded()
            return module

        importlib.import_module = _wrapped_import_module  # type: ignore[assignment]
        logger.warning("COINBASE_EXECUTION_FAILOVER_INSTALL_COMPLETE patched=%s", _PATCHED)
