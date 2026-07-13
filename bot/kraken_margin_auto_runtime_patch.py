"""Runtime convergence bridge for account-scoped Kraken spot margin."""

from __future__ import annotations

import builtins
import logging
import os
import sys
import threading
from types import ModuleType
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger("nija.kraken_margin_auto_runtime")
_MARKER = "20260713-kraken-margin-v1"
_ORIGINAL_IMPORT: Optional[Callable[..., Any]] = None
_LOCK = threading.RLock()
_PATCHED_MODULES: set[tuple[str, int]] = set()


def _is_kraken(broker: Any) -> bool:
    if broker is None:
        return False
    values = (
        type(broker).__name__,
        getattr(broker, "NAME", ""),
        getattr(getattr(broker, "broker_type", None), "value", getattr(broker, "broker_type", "")),
    )
    return any("kraken" in str(value or "").lower() for value in values)


def _account_id(broker: Any, metadata: Dict[str, Any]) -> str:
    for value in (
        metadata.get("account_id"),
        getattr(broker, "account_identifier", None),
        getattr(broker, "account_id", None),
        getattr(broker, "user_id", None),
    ):
        text = str(value or "").strip().lower()
        if text and text not in {"none", "kraken"}:
            return text
    return "platform"


def _install_defaults() -> None:
    os.environ.setdefault("NIJA_KRAKEN_MARGIN_ENABLED", "true")
    os.environ.setdefault("NIJA_KRAKEN_AUTO_MARGIN_ENABLED", "true")
    os.environ.setdefault("NIJA_KRAKEN_MARGIN_DEFAULT_LEVERAGE", "2")
    os.environ.setdefault("NIJA_KRAKEN_AUTO_MARGIN_LONG_ONLY", "true")
    os.environ.setdefault("NIJA_KRAKEN_MARGIN_HARD_MAX_LEVERAGE", "3")


def _patch_capability_matrix(module: ModuleType) -> bool:
    matrix = getattr(module, "EXCHANGE_CAPABILITIES", None)
    market_mode = getattr(module, "MarketMode", None)
    capability_cls = getattr(module, "ExchangeCapabilities", None)
    if matrix is None or market_mode is None or capability_cls is None:
        return False
    try:
        mode = market_mode.MARGIN
        matrix._capabilities.setdefault("kraken", {})[mode] = capability_cls(
            broker_name="kraken",
            market_mode=mode,
            supports_long=True,
            supports_short=True,
            supports_margin=True,
            supports_leverage=True,
            max_leverage=3.0,
            requires_margin_account=False,
            has_stop_loss=True,
            has_take_profit=True,
            has_trailing_stop=False,
            taker_fee=0.0026,
            maker_fee=0.0016,
            spread_cost=0.001,
        )
        logger.warning("KRAKEN_MARGIN_CAPABILITY_INSTALLED marker=%s max_leverage=3x", _MARKER)
        return True
    except Exception as exc:
        logger.warning("KRAKEN_MARGIN_CAPABILITY_INSTALL_FAILED marker=%s error=%s", _MARKER, exc)
        return False


def _normalize_margin_result(result: Any, *, size_usd: float, metadata: Dict[str, Any]) -> tuple[float, float]:
    if isinstance(result, tuple) and len(result) >= 2:
        return float(result[0] or 0.0), float(result[1] or size_usd)
    if not isinstance(result, dict):
        raise RuntimeError(f"Unsupported Kraken margin response: {result!r}")
    status = str(result.get("status") or result.get("state") or "").strip().lower()
    if status in {"error", "failed", "rejected", "canceled", "cancelled"}:
        raise RuntimeError(str(result.get("error") or result.get("message") or status))
    fill_price = float(
        result.get("filled_price")
        or result.get("average_filled_price")
        or result.get("average_fill_price")
        or result.get("avg_price")
        or result.get("price")
        or metadata.get("price_hint_usd")
        or 0.0
    )
    filled_usd = float(
        result.get("filled_size_usd")
        or result.get("filled_value")
        or result.get("notional_usd")
        or result.get("size_usd")
        or size_usd
    )
    order_id = result.get("order_id") or result.get("id") or result.get("exchange_order_id")
    if fill_price <= 0 and not order_id:
        raise RuntimeError(f"Kraken margin order acknowledged without fill price/order id: {result!r}")
    return fill_price, filled_usd


def _patch_router(module: ModuleType) -> bool:
    cls = getattr(module, "MultiBrokerExecutionRouter", None)
    if not isinstance(cls, type):
        return False
    current = getattr(cls, "_dispatch_direct_broker_market_order", None)
    if not callable(current):
        return False
    if getattr(current, "_nija_kraken_margin_dispatch_v1", False):
        return True
    original = current

    def dispatch_direct_broker_market_order(
        broker: Any,
        *,
        symbol: str,
        side: str,
        size_usd: float,
        metadata: Dict[str, Any],
    ) -> tuple[float, float]:
        meta = dict(metadata or {})
        leverage = min(3, max(1, int(float(meta.get("leverage") or 1))))
        if not _is_kraken(broker) or leverage <= 1:
            return original(
                broker,
                symbol=symbol,
                side=side,
                size_usd=size_usd,
                metadata=meta,
            )

        reduce_only = meta.get("reduce_only") is True
        account = _account_id(broker, meta)
        try:
            from bot.kraken_margin_engine import get_margin_engine, margin_account_scope
            engine = get_margin_engine(account_id=account, adapter=broker)
            allowed, reason = engine.is_margin_trade_allowed(
                is_reducing=reduce_only,
                adapter=broker,
            )
            pair_values = engine.get_pair_leverages(symbol, side, adapter=broker)
            if not allowed:
                raise RuntimeError(reason)
            if leverage not in pair_values:
                raise RuntimeError(f"pair_leverage_unavailable:{pair_values or 'none'}")
            submit = getattr(broker, "place_market_order", None)
            if not callable(submit):
                raise RuntimeError(f"Broker {broker!r} has no place_market_order method")
            logger.critical(
                "KRAKEN_MARGIN_ORDER_COMPILED marker=%s account=%s symbol=%s side=%s "
                "notional=$%.2f leverage=%sx reduce_only=%s margin_mode_payload=false",
                _MARKER, account, symbol, side, float(size_usd), leverage, reduce_only,
            )
            with margin_account_scope(account, adapter=broker):
                result = submit(
                    symbol,
                    side,
                    float(size_usd),
                    size_type="quote",
                    leverage=leverage,
                    reduce_only=reduce_only,
                    margin_mode=None,
                )
            fill_price, filled_usd = _normalize_margin_result(
                result,
                size_usd=float(size_usd),
                metadata=meta,
            )
            logger.critical(
                "KRAKEN_MARGIN_ORDER_ACK marker=%s account=%s symbol=%s leverage=%sx "
                "reduce_only=%s",
                _MARKER, account, symbol, leverage, reduce_only,
            )
            return fill_price, filled_usd
        except Exception as exc:
            logger.error(
                "KRAKEN_MARGIN_DISPATCH_BLOCKED marker=%s account=%s symbol=%s side=%s "
                "leverage=%sx reduce_only=%s reason=%s spot_fallback=false",
                _MARKER, account, symbol, side, leverage, reduce_only, exc,
            )
            raise

    setattr(dispatch_direct_broker_market_order, "_nija_kraken_margin_dispatch_v1", True)
    setattr(dispatch_direct_broker_market_order, "__wrapped__", original)
    setattr(cls, "_dispatch_direct_broker_market_order", staticmethod(dispatch_direct_broker_market_order))
    logger.warning("KRAKEN_MARGIN_ROUTER_BRIDGE_PATCHED marker=%s", _MARKER)
    return True


def _patch_kraken_adapter(module: ModuleType) -> bool:
    patched = False
    for name in dir(module):
        cls = getattr(module, name, None)
        if not isinstance(cls, type) or "kraken" not in name.lower():
            continue
        current = getattr(cls, "place_market_order", None)
        if not callable(current) or getattr(current, "_nija_kraken_margin_fail_closed_v1", False):
            continue
        original = current

        def place_market_order(
            self: Any,
            symbol: str,
            side: str,
            size: float,
            size_type: str = "quote",
            leverage: int = 1,
            reduce_only: Optional[bool] = None,
            margin_mode: Optional[str] = None,
            _original=original,
        ) -> Any:
            lev = min(3, max(1, int(float(leverage or 1))))
            if lev <= 1:
                return _original(
                    self,
                    symbol,
                    side,
                    size,
                    size_type=size_type,
                    leverage=1,
                    reduce_only=reduce_only,
                    margin_mode=None,
                )

            explicit_reduce = reduce_only is True
            account = _account_id(self, {})
            try:
                from bot.kraken_margin_engine import get_margin_engine, margin_account_scope
                engine = get_margin_engine(account_id=account, adapter=self)
                allowed, reason = engine.is_margin_trade_allowed(
                    is_reducing=explicit_reduce,
                    adapter=self,
                )
                pair_values = engine.get_pair_leverages(symbol, side, adapter=self)
                if not allowed:
                    detail = reason
                elif lev not in pair_values:
                    detail = f"pair_leverage_unavailable:{pair_values or 'none'}"
                else:
                    detail = ""
                if detail:
                    logger.error(
                        "KRAKEN_MARGIN_ADAPTER_BLOCKED marker=%s account=%s symbol=%s side=%s "
                        "leverage=%sx reduce_only=%s reason=%s spot_fallback=false",
                        _MARKER, account, symbol, side, lev, explicit_reduce, detail,
                    )
                    return {
                        "order_id": None,
                        "symbol": symbol,
                        "side": side,
                        "size": size,
                        "status": "error",
                        "error": f"KRAKEN_MARGIN_BLOCKED:{detail}",
                        "leverage": lev,
                        "spot_fallback": False,
                    }
                with margin_account_scope(account, adapter=self):
                    return _original(
                        self,
                        symbol,
                        side,
                        size,
                        size_type=size_type,
                        leverage=lev,
                        reduce_only=explicit_reduce,
                        margin_mode=None,
                    )
            except Exception as exc:
                return {
                    "order_id": None,
                    "symbol": symbol,
                    "side": side,
                    "size": size,
                    "status": "error",
                    "error": f"KRAKEN_MARGIN_PREFLIGHT_FAILED:{exc}",
                    "leverage": lev,
                    "spot_fallback": False,
                }

        setattr(place_market_order, "_nija_kraken_margin_fail_closed_v1", True)
        setattr(place_market_order, "__wrapped__", original)
        setattr(cls, "place_market_order", place_market_order)
        patched = True
        logger.warning("KRAKEN_MARGIN_ADAPTER_FAIL_CLOSED_PATCHED marker=%s class=%s", _MARKER, name)
    return patched


def _patch_module(module: ModuleType) -> bool:
    key = (str(getattr(module, "__name__", "")), id(module))
    with _LOCK:
        if key in _PATCHED_MODULES:
            return True
        name = str(getattr(module, "__name__", ""))
        patched = False
        if name.endswith("exchange_capabilities"):
            patched = _patch_capability_matrix(module) or patched
        if name.endswith("multi_broker_execution_router"):
            patched = _patch_router(module) or patched
        if name.endswith(("broker_integration", "kraken_broker", "broker_manager")):
            patched = _patch_kraken_adapter(module) or patched
        if patched:
            _PATCHED_MODULES.add(key)
        return patched


def _patch_loaded() -> None:
    suffixes = (
        "exchange_capabilities",
        "multi_broker_execution_router",
        "broker_integration",
        "kraken_broker",
        "broker_manager",
    )
    for name, module in list(sys.modules.items()):
        if isinstance(module, ModuleType) and name.endswith(suffixes):
            try:
                _patch_module(module)
            except Exception as exc:
                logger.debug("KRAKEN_MARGIN_PATCH_WAIT module=%s error=%s", name, exc)


def install_import_hook() -> None:
    global _ORIGINAL_IMPORT
    _install_defaults()
    _patch_loaded()
    if _ORIGINAL_IMPORT is not None:
        return
    _ORIGINAL_IMPORT = builtins.__import__
    local = threading.local()

    def import_hook(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
        module = _ORIGINAL_IMPORT(name, globals, locals, fromlist, level)  # type: ignore[misc]
        if getattr(local, "active", False):
            return module
        local.active = True
        try:
            _patch_loaded()
        finally:
            local.active = False
        return module

    builtins.__import__ = import_hook  # type: ignore[assignment]
    _patch_loaded()
    logger.critical(
        "KRAKEN_MARGIN_AUTO_RUNTIME_INSTALLED marker=%s enabled=%s auto=%s "
        "default_leverage=%s hard_max=3x long_only=%s",
        _MARKER,
        os.environ.get("NIJA_KRAKEN_MARGIN_ENABLED"),
        os.environ.get("NIJA_KRAKEN_AUTO_MARGIN_ENABLED"),
        os.environ.get("NIJA_KRAKEN_MARGIN_DEFAULT_LEVERAGE"),
        os.environ.get("NIJA_KRAKEN_AUTO_MARGIN_LONG_ONLY"),
    )


__all__ = ["install_import_hook", "_patch_capability_matrix", "_patch_router"]
