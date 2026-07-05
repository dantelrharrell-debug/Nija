from __future__ import annotations

import importlib
import logging
import sys
from types import ModuleType
from typing import Any, Callable, Optional

logger = logging.getLogger("nija.trading_engine_strategy_wrapper")
_ORIGINAL_IMPORT_MODULE: Optional[Callable[..., Any]] = None
_PATCHED = False


def _looks_like_strategy(obj: Any) -> bool:
    return callable(getattr(obj, "run_cycle", None)) and hasattr(obj, "broker")


def _looks_like_broker(obj: Any) -> bool:
    if obj is None:
        return False
    if _looks_like_strategy(obj):
        return False
    return bool(
        getattr(obj, "connected", False)
        or callable(getattr(obj, "connect", None))
        or callable(getattr(obj, "get_account_balance", None))
        or callable(getattr(obj, "place_market_order", None))
    )


def _broker_label(broker: Any) -> str:
    btype = getattr(broker, "broker_type", None)
    if btype is not None:
        raw = getattr(btype, "value", btype)
        if raw:
            return str(raw).strip().lower()
    name = type(broker).__name__.replace("Broker", "").strip().lower()
    return name or "primary"


def _wrap_broker_as_strategy(broker: Any):
    from bot.trading_strategy import TradingStrategy

    broker_name = _broker_label(broker)
    strategy = TradingStrategy(broker_results={broker_name: {"broker": broker}})
    strategy.broker = broker

    apex = getattr(strategy, "apex", None)
    if apex is not None:
        try:
            update = getattr(apex, "update_broker_client", None)
            if callable(update):
                update(broker)
            else:
                setattr(apex, "broker_client", broker)
        except Exception as exc:  # noqa: BLE001
            logger.warning("TRADING_ENGINE_STRATEGY_WRAPPER_APEX_REBIND_FAILED err=%s", exc)

    execution_engine = getattr(strategy, "execution_engine", None)
    if execution_engine is not None:
        try:
            setattr(execution_engine, "broker_client", broker)
        except Exception:
            pass

    logger.critical(
        "TRADING_ENGINE_STRATEGY_WRAPPED broker=%s broker_type=%s strategy=%s symbols=%d apex=%s",
        broker_name,
        type(broker).__name__,
        type(strategy).__name__,
        len(getattr(strategy, "symbols", []) or []),
        type(getattr(strategy, "apex", None)).__name__,
    )
    return strategy


def _patch_module(module: ModuleType) -> bool:
    global _PATCHED
    original = getattr(module, "start_trading_engine", None)
    if not callable(original):
        return False
    if getattr(original, "_nija_strategy_wrapper_patched", False):
        _PATCHED = True
        return True

    def _patched_start_trading_engine(strategy_or_broker: Any, *args: Any, **kwargs: Any):
        runtime = strategy_or_broker
        if _looks_like_broker(strategy_or_broker):
            runtime = _wrap_broker_as_strategy(strategy_or_broker)
        return original(runtime, *args, **kwargs)

    setattr(_patched_start_trading_engine, "_nija_strategy_wrapper_patched", True)
    setattr(module, "start_trading_engine", _patched_start_trading_engine)
    _PATCHED = True
    logger.warning("TRADING_ENGINE_STRATEGY_WRAPPER_PATCHED module=%s", module.__name__)
    return True


def _patch_loaded() -> bool:
    patched = False
    for name in ("bot.nija_core_loop", "nija_core_loop"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            patched = _patch_module(module) or patched
    return patched


def install_import_hook() -> None:
    global _ORIGINAL_IMPORT_MODULE
    _patch_loaded()
    if _ORIGINAL_IMPORT_MODULE is not None:
        logger.warning("TRADING_ENGINE_STRATEGY_WRAPPER_INSTALL_COMPLETE already_installed=True patched=%s", _PATCHED)
        return
    _ORIGINAL_IMPORT_MODULE = importlib.import_module

    def _wrapped_import_module(name: str, package: str | None = None):
        module = _ORIGINAL_IMPORT_MODULE(name, package)  # type: ignore[misc]
        if name in {"bot.nija_core_loop", "nija_core_loop"}:
            _patch_module(module)
        return module

    importlib.import_module = _wrapped_import_module  # type: ignore[assignment]
    logger.warning("TRADING_ENGINE_STRATEGY_WRAPPER_INSTALL_COMPLETE patched=%s", _PATCHED)


def install() -> None:
    install_import_hook()
