from __future__ import annotations

import importlib
import logging
import os
import sys
from types import ModuleType
from typing import Any, Callable, Optional

logger = logging.getLogger("nija.trading_engine_strategy_wrapper")
_MARKER = "20260709at"
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


def _resolve_trading_strategy_class() -> type | None:
    """Resolve TradingStrategy without crashing during circular imports."""
    for module_name in ("bot.trading_strategy", "trading_strategy"):
        module = sys.modules.get(module_name)
        if isinstance(module, ModuleType):
            cls = getattr(module, "TradingStrategy", None)
            if isinstance(cls, type):
                return cls
    for module_name in ("bot.trading_strategy", "trading_strategy"):
        try:
            module = importlib.import_module(module_name)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "TRADING_ENGINE_STRATEGY_CLASS_IMPORT_DEFERRED marker=%s module=%s err=%s",
                _MARKER,
                module_name,
                exc,
            )
            continue
        cls = getattr(module, "TradingStrategy", None)
        if isinstance(cls, type):
            return cls
    return None


class _BrokerRuntimeStrategy:
    """Minimal live-loop runtime used only when TradingStrategy is unavailable.

    This is not a trade bypass. It still routes through NIJAApexStrategyV71,
    NijaCoreLoop, broker adapters, runtime authority, ECEL, and all downstream
    risk/execution gates. Its only purpose is preventing a startup ImportError
    from killing the process before the normal strategy class is available.
    """

    def __init__(self, broker: Any) -> None:
        self.broker = broker
        self.broker_manager = None
        self.multi_account_manager = None
        self.apex = None
        self.nija_core_loop = None
        self.execution_engine = None
        self.symbols: list[str] = []
        self._wire_runtime()

    def _wire_runtime(self) -> None:
        try:
            try:
                from bot.broker_manager import get_broker_manager
            except ImportError:
                from broker_manager import get_broker_manager  # type: ignore[import]
            self.broker_manager = get_broker_manager()
        except Exception as exc:  # noqa: BLE001
            logger.warning("TRADING_ENGINE_STRATEGY_FALLBACK_BROKER_MANAGER_UNAVAILABLE marker=%s err=%s", _MARKER, exc)
        try:
            try:
                from bot.multi_account_broker_manager import multi_account_broker_manager
            except ImportError:
                from multi_account_broker_manager import multi_account_broker_manager  # type: ignore[import]
            self.multi_account_manager = multi_account_broker_manager
        except Exception as exc:  # noqa: BLE001
            logger.debug("TRADING_ENGINE_STRATEGY_FALLBACK_MABM_UNAVAILABLE marker=%s err=%s", _MARKER, exc)
        try:
            try:
                from bot.nija_apex_strategy_v71 import NIJAApexStrategyV71
            except ImportError:
                from nija_apex_strategy_v71 import NIJAApexStrategyV71  # type: ignore[import]
            self.apex = NIJAApexStrategyV71(broker_client=self.broker)
            self.execution_engine = getattr(self.apex, "execution_engine", None)
        except Exception as exc:  # noqa: BLE001
            logger.critical("TRADING_ENGINE_STRATEGY_FALLBACK_APEX_UNAVAILABLE marker=%s err=%s", _MARKER, exc)
            return
        try:
            try:
                from bot.nija_core_loop import get_nija_core_loop
            except ImportError:
                from nija_core_loop import get_nija_core_loop  # type: ignore[import]
            self.nija_core_loop = get_nija_core_loop(
                apex_strategy=self.apex,
                max_positions=max(1, int(os.environ.get("NIJA_MAX_POSITIONS", "5") or 5)),
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("TRADING_ENGINE_STRATEGY_FALLBACK_CORE_LOOP_UNAVAILABLE marker=%s err=%s", _MARKER, exc)
        self._maybe_refresh_symbols(force=True)
        logger.critical(
            "TRADING_ENGINE_STRATEGY_FALLBACK_RUNTIME_READY marker=%s broker=%s apex=%s core=%s symbols=%d",
            _MARKER,
            _broker_label(self.broker),
            type(self.apex).__name__ if self.apex is not None else "None",
            type(self.nija_core_loop).__name__ if self.nija_core_loop is not None else "None",
            len(self.symbols),
        )

    def _ensure_nija_wiring(self) -> None:
        if self.apex is not None and self.nija_core_loop is None:
            self._wire_runtime()

    def _maybe_refresh_symbols(self, *, force: bool = False) -> None:
        symbols: list[str] = []
        for owner in (self.apex, self.broker):
            if owner is None:
                continue
            for attr in ("symbols", "tradable_symbols", "supported_symbols"):
                value = getattr(owner, attr, None)
                if isinstance(value, (list, tuple, set)):
                    symbols.extend(str(s).strip().upper() for s in value if str(s).strip())
        if not symbols:
            raw = os.environ.get("NIJA_SYMBOLS", "ADA-USD,BTC-USD,ETH-USD,SOL-USD,XRP-USD")
            symbols = [s.strip().upper() for s in raw.split(",") if s.strip()]
        self.symbols = list(dict.fromkeys(symbols))

    def _balance(self) -> float:
        for attr in ("_last_known_balance", "last_known_balance", "cached_balance", "last_balance"):
            try:
                value = getattr(self.broker, attr, None)
                if value is not None:
                    amount = float(value or 0.0)
                    if amount > 0.0:
                        return amount
            except Exception:
                pass
        getter = getattr(self.broker, "get_account_balance", None)
        if callable(getter):
            try:
                return float(getter() or 0.0)
            except Exception:
                return 0.0
        return 0.0

    def run_cycle(self) -> float:
        if self.nija_core_loop is None or self.apex is None:
            logger.warning("TRADING_ENGINE_STRATEGY_FALLBACK_CYCLE_SKIPPED marker=%s reason=runtime_not_wired", _MARKER)
            return float(os.environ.get("NIJA_FALLBACK_RUNTIME_RETRY_S", "15") or 15.0)
        self._maybe_refresh_symbols(force=False)
        try:
            result = self.nija_core_loop.run_scan_phase(
                broker=self.broker,
                balance=self._balance(),
                symbols=self.symbols,
                open_positions_count=0,
            )
            return float(getattr(result, "next_interval", os.environ.get("NIJA_CYCLE_SECONDS", "60")) or 60.0)
        except Exception as exc:  # noqa: BLE001
            logger.exception("TRADING_ENGINE_STRATEGY_FALLBACK_CYCLE_ERROR marker=%s err=%s", _MARKER, exc)
            return float(os.environ.get("NIJA_FALLBACK_RUNTIME_RETRY_S", "15") or 15.0)


def _wrap_broker_as_strategy(broker: Any):
    TradingStrategy = _resolve_trading_strategy_class()
    broker_name = _broker_label(broker)
    if TradingStrategy is None:
        logger.critical(
            "TRADING_ENGINE_STRATEGY_IMPORT_FALLBACK marker=%s broker=%s reason=TradingStrategy_class_unavailable action=use_minimal_runtime",
            _MARKER,
            broker_name,
        )
        strategy = _BrokerRuntimeStrategy(broker)
    else:
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
            logger.warning("TRADING_ENGINE_STRATEGY_WRAPPER_APEX_REBIND_FAILED marker=%s err=%s", _MARKER, exc)

    execution_engine = getattr(strategy, "execution_engine", None)
    if execution_engine is not None:
        try:
            setattr(execution_engine, "broker_client", broker)
        except Exception:
            pass

    logger.critical(
        "TRADING_ENGINE_STRATEGY_WRAPPED marker=%s broker=%s broker_type=%s strategy=%s symbols=%d apex=%s",
        _MARKER,
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
    if getattr(original, "_nija_strategy_wrapper_patched_20260709at", False):
        _PATCHED = True
        return True

    def _patched_start_trading_engine(strategy_or_broker: Any, *args: Any, **kwargs: Any):
        runtime = strategy_or_broker
        if _looks_like_broker(strategy_or_broker):
            runtime = _wrap_broker_as_strategy(strategy_or_broker)
        return original(runtime, *args, **kwargs)

    setattr(_patched_start_trading_engine, "_nija_strategy_wrapper_patched_20260709at", True)
    setattr(module, "start_trading_engine", _patched_start_trading_engine)
    _PATCHED = True
    logger.warning("TRADING_ENGINE_STRATEGY_WRAPPER_PATCHED marker=%s module=%s", _MARKER, module.__name__)
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
        logger.warning("TRADING_ENGINE_STRATEGY_WRAPPER_INSTALL_COMPLETE marker=%s already_installed=True patched=%s", _MARKER, _PATCHED)
        return
    _ORIGINAL_IMPORT_MODULE = importlib.import_module

    def _wrapped_import_module(name: str, package: str | None = None):
        module = _ORIGINAL_IMPORT_MODULE(name, package)  # type: ignore[misc]
        if name in {"bot.nija_core_loop", "nija_core_loop"}:
            _patch_module(module)
        return module

    importlib.import_module = _wrapped_import_module  # type: ignore[assignment]
    logger.warning("TRADING_ENGINE_STRATEGY_WRAPPER_INSTALL_COMPLETE marker=%s patched=%s", _MARKER, _PATCHED)


def install() -> None:
    install_import_hook()
